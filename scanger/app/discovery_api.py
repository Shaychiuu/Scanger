"""Web discovery routes of the Scanger API (M04).

Plan a run (from a stored reference image with Cursor, or from the owner's own
queries), start it on SerpApi, follow it, stop it, and read it back: leads,
offline replay, the full text log and the saved raw responses. The logic is in
`scanger.discovery_service`; runs are the CLI's JSON records.
"""

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session as OrmSession

from scanger import assets, discovery_service
from scanger.deps import get_data_root, get_db
from scanger.discover import HARD_MAX_CALLS, DiscoveryError, RunNotFound, SettingsError
from scanger.discovery_service import ClientFactory, RunConflict, RunOptions
from scanger.serpapi import SerpApiClient

router = APIRouter(prefix="/discovery", tags=["discovery"])


def get_client_factory() -> ClientFactory:
    return SerpApiClient


@contextmanager
def _errors() -> Iterator[None]:
    try:
        yield
    except (RunNotFound, assets.AssetNotFound, assets.AssetFileMissing) as exc:
        raise HTTPException(404, detail=str(exc)) from exc
    except RunConflict as exc:
        raise HTTPException(409, detail=str(exc)) from exc
    except (DiscoveryError, SettingsError, assets.AssetError) as exc:
        raise HTTPException(422, detail=str(exc)) from exc


class PlanBody(BaseModel):
    source: Literal["image", "queries"]
    asset_id: uuid.UUID | None = None
    text: str = Field(default="", max_length=2000)
    queries: dict[str, dict[str, str | None]] | None = None
    from_record: uuid.UUID | None = None
    markets: list[str] | None = Field(default=None, max_length=50)
    max_calls: int | None = Field(default=None, ge=1, le=HARD_MAX_CALLS)
    no_modifiers: bool = False
    no_sites: bool = False


@router.get("/settings")
def get_settings():
    with _errors():
        return discovery_service.settings_info()


@router.get("/account")
def get_account(client_factory: ClientFactory = Depends(get_client_factory)):
    with _errors():
        return discovery_service.account_status(client_factory)


@router.get("/runs")
def list_runs(root: Path = Depends(get_data_root)):
    return discovery_service.list_runs(root)


@router.post("/runs", status_code=201)
def create_run(body: PlanBody, db: OrmSession = Depends(get_db), root: Path = Depends(get_data_root)):
    """Save a plan. With an image this calls Cursor; it never calls SerpApi."""
    options = RunOptions(body.markets, body.max_calls, body.no_modifiers, body.no_sites)
    with _errors():
        settings = discovery_service.load_settings(options)
        if body.source == "image":
            if body.asset_id is None:
                raise DiscoveryError("Upload a reference image first.")
            asset, path = assets.get_asset_file(db, body.asset_id, root)
            run = discovery_service.plan_from_image(
                root, settings, path.read_bytes(), asset.original_name, body.text, str(asset.id))
            return {"run": run, "notes": []}
        run, notes = discovery_service.plan_from_queries(root, settings, body.queries or {}, body.from_record)
        return {"run": run, "notes": notes}


@router.get("/runs/{run_id}")
def get_run(run_id: uuid.UUID, root: Path = Depends(get_data_root)):
    with _errors():
        return discovery_service.get_run(root, run_id)


@router.post("/runs/{run_id}/start")
def start_run(run_id: uuid.UUID, root: Path = Depends(get_data_root),
              client_factory: ClientFactory = Depends(get_client_factory)):
    """Start a planned run in the background; poll GET /runs/{id} for progress."""
    with _errors():
        return discovery_service.start_run(root, run_id, client_factory)


@router.post("/runs/{run_id}/cancel")
def cancel_run(run_id: uuid.UUID, root: Path = Depends(get_data_root)):
    with _errors():
        return discovery_service.cancel_run(root, run_id)


@router.get("/runs/{run_id}/replay")
def replay_run(run_id: uuid.UUID, root: Path = Depends(get_data_root)):
    """Leads rebuilt offline from the saved responses; the run is not changed."""
    with _errors():
        return discovery_service.replay(root, run_id)


@router.get("/runs/{run_id}/log")
def run_log(run_id: uuid.UUID, replayed: bool = False, root: Path = Depends(get_data_root)):
    with _errors():
        return {"text": discovery_service.run_log(root, run_id, replayed)}


@router.get("/runs/{run_id}/raw/{index}")
def raw_response(run_id: uuid.UUID, index: int, root: Path = Depends(get_data_root)):
    with _errors():
        return discovery_service.raw_response(root, run_id, index)
