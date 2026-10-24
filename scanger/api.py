"""Scanger's own HTTP API (separate from the upstream VisualMatch API).

The frontend talks only to this API. Searches are forwarded to the VisualMatch
API through `scanger.retrieval`, and everything is saved in PostgreSQL.

Run from the repository root:
    uvicorn scanger.api:app --host 127.0.0.1 --port 8010
"""

import uuid
from collections.abc import Iterator
from contextlib import asynccontextmanager
from functools import lru_cache
from pathlib import Path

from fastapi import Depends, FastAPI, File, HTTPException, Response, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session as OrmSession

from scanger import assets, catalogue, history
from scanger.config import (
    UploadLimits,
    data_root,
    upload_limits,
    visualmatch_api_url,
    visualmatch_model,
)
from scanger.db import get_session_factory
from scanger.models import Asset, SearchResult, SearchRun, Session, Turn
from scanger.retrieval import RetrievalAdapter, VisualMatchHttpAdapter

IMAGE_HEADERS = {"X-Content-Type-Options": "nosniff", "Cache-Control": "private, max-age=3600"}


@asynccontextmanager
async def lifespan(app: FastAPI):
    with get_session_factory()() as db:
        count = history.reconcile_interrupted_runs(db)
    if count:
        print(f"Marked {count} unfinished search run(s) as interrupted.")
    yield


app = FastAPI(title="Scanger API", lifespan=lifespan)


def get_db() -> Iterator[OrmSession]:
    with get_session_factory()() as db:
        yield db


def get_data_root() -> Path:
    return data_root()


def get_limits() -> UploadLimits:
    return upload_limits()


@lru_cache
def get_adapter() -> RetrievalAdapter:
    return VisualMatchHttpAdapter(visualmatch_api_url(), visualmatch_model())


# --- serialisation -----------------------------------------------------------


def _asset_json(asset: Asset | None) -> dict | None:
    if asset is None:
        return None
    return {
        "id": str(asset.id),
        "url": f"/assets/{asset.id}",
        "original_name": asset.original_name,
        "mime_type": asset.mime_type,
        "byte_size": asset.byte_size,
        "width": asset.width,
        "height": asset.height,
        "sha256": asset.sha256,
    }


def _session_json(session: Session) -> dict:
    return {
        "id": str(session.id),
        "title": session.title,
        "created_at": session.created_at.isoformat(),
        "updated_at": session.updated_at.isoformat(),
    }


def _result_json(result: SearchResult) -> dict:
    return {
        "rank": result.rank,
        "source_kind": result.source_kind,
        "source_item_id": result.source_item_id,
        "raw_score": result.raw_score,
        "metadata": result.item_metadata,
        "image_url": f"/results/{result.run_id}/{result.rank}/image",
    }


def _run_json(run: SearchRun) -> dict:
    return {
        "id": str(run.id),
        "attempt": run.attempt,
        "status": run.status,
        "search_mode": run.search_mode,
        "result_limit": run.result_limit,
        "configuration_version": run.configuration_version,
        "configuration": run.configuration,
        "dataset_version": run.dataset_version,
        "model_name": run.model_name,
        "index_version": run.index_version,
        "score_kind": run.score_kind,
        "higher_is_better": run.higher_is_better,
        "error_message": run.error_message,
        "created_at": run.created_at.isoformat(),
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
        "results": [_result_json(r) for r in run.results],
    }


def _turn_json(turn: Turn) -> dict:
    return {
        "id": str(turn.id),
        "ordinal": turn.ordinal,
        "prompt_text": turn.prompt_text,
        "reference_asset": _asset_json(turn.reference_asset),
        "created_at": turn.created_at.isoformat(),
        "runs": [_run_json(run) for run in turn.runs],
    }


# --- routes ------------------------------------------------------------------


class SessionBody(BaseModel):
    title: str = Field(max_length=history.MAX_TITLE_LENGTH)


class TurnBody(BaseModel):
    prompt_text: str | None = Field(default=None, max_length=2000)
    reference_asset_id: uuid.UUID | None = None
    alpha: float = Field(default=0.5, ge=0.0, le=1.0)
    client_request_id: uuid.UUID | None = None


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/sessions")
def list_sessions(db: OrmSession = Depends(get_db)):
    return [_session_json(s) for s in history.list_sessions(db)]


@app.post("/sessions", status_code=201)
def create_session(body: SessionBody, db: OrmSession = Depends(get_db)):
    try:
        return _session_json(history.create_session(db, body.title))
    except history.InvalidRequest as exc:
        raise HTTPException(422, detail=str(exc)) from exc


@app.patch("/sessions/{session_id}")
def rename_session(session_id: uuid.UUID, body: SessionBody, db: OrmSession = Depends(get_db)):
    try:
        return _session_json(history.rename_session(db, session_id, body.title))
    except history.NotFound as exc:
        raise HTTPException(404, detail="session_not_found") from exc
    except history.InvalidRequest as exc:
        raise HTTPException(422, detail=str(exc)) from exc


@app.get("/sessions/{session_id}")
def get_session(session_id: uuid.UUID, db: OrmSession = Depends(get_db)):
    try:
        session = history.get_session_detail(db, session_id)
    except history.NotFound as exc:
        raise HTTPException(404, detail="session_not_found") from exc
    return {**_session_json(session), "turns": [_turn_json(t) for t in session.turns]}


@app.post("/sessions/{session_id}/turns", status_code=201)
def create_turn(
    session_id: uuid.UUID,
    body: TurnBody,
    db: OrmSession = Depends(get_db),
    root: Path = Depends(get_data_root),
    adapter: RetrievalAdapter = Depends(get_adapter),
):
    """Save the query, run retrieval and return the turn (blocks until done)."""
    request = history.TurnRequest(
        prompt_text=body.prompt_text,
        reference_asset_id=body.reference_asset_id,
        alpha=body.alpha,
        client_request_id=body.client_request_id,
    )
    try:
        turn = history.submit_turn(db, session_id, request, adapter, root)
    except history.NotFound as exc:
        raise HTTPException(404, detail="session_not_found") from exc
    except history.InvalidRequest as exc:
        raise HTTPException(422, detail=str(exc)) from exc
    db.expire_all()
    return _turn_json(turn)


@app.post("/turns/{turn_id}/runs", status_code=201)
def retry_turn(
    turn_id: uuid.UUID,
    db: OrmSession = Depends(get_db),
    root: Path = Depends(get_data_root),
    adapter: RetrievalAdapter = Depends(get_adapter),
):
    """Run a saved turn again as a new run; earlier results are kept."""
    try:
        run = history.retry_turn(db, turn_id, adapter, root)
    except history.NotFound as exc:
        raise HTTPException(404, detail="turn_not_found") from exc
    db.expire_all()
    return _run_json(run)


@app.post("/assets", status_code=201)
async def upload_asset(
    file: UploadFile = File(...),
    db: OrmSession = Depends(get_db),
    root: Path = Depends(get_data_root),
    limits: UploadLimits = Depends(get_limits),
):
    # Read at most limit+1 bytes so an oversized upload is not held in memory.
    data = await file.read(limits.max_bytes + 1)
    try:
        asset = assets.store_image(db, data, file.filename, root, limits)
    except assets.UploadTooLarge as exc:
        raise HTTPException(413, detail=str(exc)) from exc
    except assets.InvalidImage as exc:
        raise HTTPException(422, detail=str(exc)) from exc
    return _asset_json(asset)


@app.get("/assets/{asset_id}")
def get_asset(
    asset_id: uuid.UUID,
    db: OrmSession = Depends(get_db),
    root: Path = Depends(get_data_root),
):
    """Serve one stored image by ID. Paths are never taken from the request."""
    try:
        asset, path = assets.get_asset_file(db, asset_id, root)
    except assets.AssetNotFound as exc:
        raise HTTPException(404, detail="asset_not_found") from exc
    except assets.AssetFileMissing as exc:
        raise HTTPException(404, detail="asset_file_missing") from exc
    except assets.InvalidStorageKey as exc:
        raise HTTPException(500, detail="asset_storage_key_invalid") from exc
    return FileResponse(path, media_type=asset.mime_type, headers=IMAGE_HEADERS)


@app.get("/results/{run_id}/{rank}/image")
def get_result_image(run_id: uuid.UUID, rank: int, db: OrmSession = Depends(get_db)):
    """Serve the catalogue image of one saved result."""
    result = db.get(SearchResult, (run_id, rank))
    if result is None:
        raise HTTPException(404, detail="result_not_found")
    if result.source_kind != "dataset":
        raise HTTPException(404, detail="result_image_unavailable")
    try:
        data, mime_type = catalogue.load_dataset_image(result.image_locator, result.source_item_id)
    except catalogue.CatalogueImageUnavailable as exc:
        raise HTTPException(404, detail="result_image_unavailable") from exc
    return Response(content=data, media_type=mime_type, headers=IMAGE_HEADERS)
