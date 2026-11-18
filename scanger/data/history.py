"""Sessions, turns and search runs.

A search is saved in three commits: (1) the turn and a pending run, before any
inference; (2) the run marked running; (3) the ranked results together with the
completed status, or the failed status with its error and no results. Runs left
pending/running by a stopped API are marked interrupted on the next start.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session as OrmSession
from sqlalchemy.orm import selectinload

from scanger import assets
from scanger.models import Asset, SearchResult, SearchRun, Session, Turn
from scanger.retrieval import QueryImage, RetrievalAdapter, RetrievalError

CONFIGURATION_VERSION = 1
MAX_TITLE_LENGTH = 200
INTERRUPTED_MESSAGE = "Interrupted: the API stopped before this run finished. Retry to run it again."


class NotFound(Exception):
    pass


class InvalidRequest(Exception):
    pass


@dataclass(frozen=True)
class TurnRequest:
    prompt_text: str | None = None
    reference_asset_id: uuid.UUID | None = None
    alpha: float = 0.5
    client_request_id: uuid.UUID | None = None


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _clean_title(title: str) -> str:
    title = (title or "").strip()
    if not title:
        raise InvalidRequest("A session title is required.")
    if len(title) > MAX_TITLE_LENGTH:
        raise InvalidRequest(f"Session titles are limited to {MAX_TITLE_LENGTH} characters.")
    return title


def derive_mode(has_image: bool, has_text: bool) -> str:
    if has_image and has_text:
        return "composed"
    if has_image:
        return "image"
    if has_text:
        return "text"
    raise InvalidRequest("Provide a reference image, a description, or both.")


# --- sessions ----------------------------------------------------------------


def create_session(db: OrmSession, title: str) -> Session:
    session = Session(title=_clean_title(title))
    db.add(session)
    db.commit()
    return session


def list_sessions(db: OrmSession) -> list[Session]:
    return list(db.scalars(select(Session).order_by(Session.updated_at.desc())))


def rename_session(db: OrmSession, session_id: uuid.UUID, title: str) -> Session:
    session = db.get(Session, session_id)
    if session is None:
        raise NotFound(f"No session {session_id}.")
    session.title = _clean_title(title)
    session.updated_at = _now()
    db.commit()
    return session


def get_session_detail(db: OrmSession, session_id: uuid.UUID) -> Session:
    session = db.scalars(
        select(Session)
        .where(Session.id == session_id)
        .options(
            selectinload(Session.turns).selectinload(Turn.reference_asset),
            selectinload(Session.turns)
            .selectinload(Turn.runs)
            .selectinload(SearchRun.results),
        )
    ).one_or_none()
    if session is None:
        raise NotFound(f"No session {session_id}.")
    return session


# --- searching ---------------------------------------------------------------


def submit_turn(
    db: OrmSession,
    session_id: uuid.UUID,
    request: TurnRequest,
    adapter: RetrievalAdapter,
    data_root: Path,
) -> Turn:
    """Save a complete query as a new turn, run it, and return the turn."""
    text = (request.prompt_text or "").strip() or None
    mode = derive_mode(request.reference_asset_id is not None, text is not None)
    if not 0.0 <= request.alpha <= 1.0:
        raise InvalidRequest("alpha must be between 0 and 1.")

    # Row lock serialises turn creation per session (ordinal + duplicate check).
    session = db.get(Session, session_id, with_for_update=True)
    if session is None:
        raise NotFound(f"No session {session_id}.")
    if request.client_request_id is not None:
        existing = db.scalars(
            select(Turn).where(
                Turn.session_id == session_id,
                Turn.client_request_id == request.client_request_id,
            )
        ).one_or_none()
        if existing is not None:
            db.commit()
            return existing
    if request.reference_asset_id is not None and db.get(Asset, request.reference_asset_id) is None:
        db.rollback()
        raise InvalidRequest(f"No asset {request.reference_asset_id}.")

    ordinal = (
        db.scalar(select(func.max(Turn.ordinal)).where(Turn.session_id == session_id)) or 0
    ) + 1
    turn = Turn(
        session_id=session_id,
        ordinal=ordinal,
        prompt_text=text,
        reference_asset_id=request.reference_asset_id,
        client_request_id=request.client_request_id,
    )
    alpha = request.alpha if mode == "composed" else None
    run = _new_run(turn, mode, attempt=1, alpha=alpha, adapter=adapter)
    session.updated_at = _now()
    db.add_all([turn, run])
    db.commit()

    _execute_run(db, run, adapter, data_root)
    return turn


def retry_turn(
    db: OrmSession, turn_id: uuid.UUID, adapter: RetrievalAdapter, data_root: Path
) -> SearchRun:
    """Run a turn's query again as a new run; earlier runs are kept unchanged."""
    turn = db.get(Turn, turn_id, with_for_update=True)
    if turn is None:
        raise NotFound(f"No turn {turn_id}.")
    last = db.scalars(
        select(SearchRun).where(SearchRun.turn_id == turn_id).order_by(SearchRun.attempt.desc())
    ).first()
    if last is None:
        mode = derive_mode(turn.reference_asset_id is not None, turn.prompt_text is not None)
        attempt, alpha = 1, (0.5 if mode == "composed" else None)
    else:
        mode, attempt = last.search_mode, last.attempt + 1
        alpha = last.configuration.get("alpha")
    run = _new_run(turn, mode, attempt=attempt, alpha=alpha, adapter=adapter)
    db.get(Session, turn.session_id).updated_at = _now()
    db.add(run)
    db.commit()

    _execute_run(db, run, adapter, data_root)
    return run


def reconcile_interrupted_runs(db: OrmSession) -> int:
    """Mark runs left pending/running by a previous process as interrupted.

    Only safe with a single API process, which is how Scanger runs.
    """
    result = db.execute(
        update(SearchRun)
        .where(SearchRun.status.in_(("pending", "running")))
        .values(status="interrupted", error_message=INTERRUPTED_MESSAGE, finished_at=_now())
    )
    db.commit()
    return result.rowcount


def _new_run(
    turn: Turn, mode: str, attempt: int, alpha: float | None, adapter: RetrievalAdapter
) -> SearchRun:
    info = adapter.info
    configuration = {"backend": info.backend}
    if alpha is not None:
        configuration["alpha"] = alpha
    return SearchRun(
        turn=turn,
        attempt=attempt,
        status="pending",
        search_mode=mode,
        result_limit=info.result_limit,
        configuration_version=CONFIGURATION_VERSION,
        configuration=configuration,
        dataset_version=info.dataset_version,
        model_name=info.model_name,
        index_version=info.index_version,
        score_kind=info.score_kind,
        higher_is_better=info.higher_is_better,
    )


def _execute_run(
    db: OrmSession, run: SearchRun, adapter: RetrievalAdapter, data_root: Path
) -> None:
    run.status = "running"
    run.started_at = _now()
    db.commit()

    turn = run.turn
    try:
        image = None
        if run.search_mode in ("image", "composed"):
            asset, path = assets.get_asset_file(db, turn.reference_asset_id, data_root)
            image = QueryImage(
                data=path.read_bytes(),
                mime_type=asset.mime_type,
                filename=path.name,
            )
        text = turn.prompt_text if run.search_mode in ("text", "composed") else None
        items = adapter.search(run.search_mode, text, image, run.configuration.get("alpha", 0.5))
        for rank, item in enumerate(items[: run.result_limit], start=1):
            db.add(
                SearchResult(
                    run_id=run.id,
                    rank=rank,
                    source_kind=item.source_kind,
                    source_item_id=item.source_item_id,
                    image_locator=item.image_locator,
                    raw_score=item.raw_score,
                    item_metadata=item.metadata,
                )
            )
        run.status = "completed"
        run.finished_at = _now()
        db.commit()
    except Exception as exc:
        db.rollback()
        run.status = "failed"
        run.error_message = _describe(exc)
        run.finished_at = _now()
        db.commit()


def _describe(exc: Exception) -> str:
    if isinstance(exc, (RetrievalError, assets.AssetError)):
        return str(exc)
    return f"{type(exc).__name__}: {exc}"[:2000]
