"""Persistence schema for M01: Session, Asset, Turn, SearchRun, SearchResult.

PostgreSQL stores history and metadata only. Image bytes live under DATA_ROOT
and are referenced by relative storage key. The FAISS index is not stored here.
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    MetaData,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

# Stable constraint names keep Alembic migrations deterministic.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

# Allowed values are enforced with CHECK constraints rather than PG enums,
# which are awkward to change in migrations.
SEARCH_MODES = ("image", "text", "composed")
RUN_STATUSES = ("pending", "running", "completed", "failed", "interrupted")


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class Session(Base):
    __tablename__ = "session"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    title: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    turns: Mapped[list["Turn"]] = relationship(
        back_populates="session", order_by="Turn.ordinal"
    )


class Asset(Base):
    __tablename__ = "asset"
    __table_args__ = (
        # Never absolute, never traversing. Validation in code is the primary guard.
        CheckConstraint(
            "storage_key NOT LIKE '/%' AND storage_key NOT LIKE '%..%'",
            name="storage_key_relative",
        ),
        CheckConstraint("byte_size > 0", name="byte_size_positive"),
        CheckConstraint("width > 0 AND height > 0", name="dimensions_positive"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    # Relative to DATA_ROOT, e.g. "uploads/<asset-id>.jpg".
    storage_key: Mapped[str] = mapped_column(String(300), unique=True)
    # Display metadata only; never used to build a path.
    original_name: Mapped[str | None] = mapped_column(String(300))
    mime_type: Mapped[str] = mapped_column(String(100))
    byte_size: Mapped[int] = mapped_column(BigInteger)
    width: Mapped[int] = mapped_column(Integer)
    height: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Turn(Base):
    __tablename__ = "turn"
    __table_args__ = (
        UniqueConstraint("session_id", "ordinal"),
        # Repeated submits of the same frontend draft map to one turn.
        UniqueConstraint("session_id", "client_request_id"),
        CheckConstraint("ordinal >= 1", name="ordinal_positive"),
        # Each turn is a complete query: an image, text, or both.
        CheckConstraint(
            "reference_asset_id IS NOT NULL OR prompt_text IS NOT NULL",
            name="has_query",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("session.id"), index=True
    )
    ordinal: Mapped[int] = mapped_column(Integer)
    prompt_text: Mapped[str | None] = mapped_column(Text)
    reference_asset_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("asset.id"), index=True
    )
    client_request_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    session: Mapped[Session] = relationship(back_populates="turns")
    reference_asset: Mapped[Asset | None] = relationship()
    runs: Mapped[list["SearchRun"]] = relationship(
        back_populates="turn", order_by="SearchRun.attempt"
    )


class SearchRun(Base):
    __tablename__ = "search_run"
    __table_args__ = (
        # A retry is a new run (next attempt) on the same turn.
        UniqueConstraint("turn_id", "attempt"),
        CheckConstraint("attempt >= 1", name="attempt_positive"),
        CheckConstraint(_in("status", RUN_STATUSES), name="status_valid"),
        CheckConstraint(_in("search_mode", SEARCH_MODES), name="search_mode_valid"),
        CheckConstraint("result_limit > 0", name="result_limit_positive"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    turn_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("turn.id"), index=True)
    attempt: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    search_mode: Mapped[str] = mapped_column(String(20))
    result_limit: Mapped[int] = mapped_column(Integer)
    # Versioned, JSON-only settings (never pickled objects). The shape is
    # identified by configuration_version so old runs stay interpretable.
    configuration_version: Mapped[int] = mapped_column(Integer, default=1)
    configuration: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    # Reproducibility: what produced the results.
    dataset_version: Mapped[str | None] = mapped_column(String(200))
    model_name: Mapped[str | None] = mapped_column(String(200))
    index_version: Mapped[str | None] = mapped_column(String(200))
    # Score semantics, so raw scores are never mistaken for probabilities.
    score_kind: Mapped[str | None] = mapped_column(String(50))
    higher_is_better: Mapped[bool | None] = mapped_column(Boolean)
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    turn: Mapped[Turn] = relationship(back_populates="runs")
    results: Mapped[list["SearchResult"]] = relationship(
        back_populates="run", order_by="SearchResult.rank"
    )


class SearchResult(Base):
    __tablename__ = "search_result"
    __table_args__ = (CheckConstraint("rank >= 1", name="rank_positive"),)

    # (run_id, rank) is the key, so ordering is unique per run.
    run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("search_run.id"), primary_key=True
    )
    rank: Mapped[int] = mapped_column(Integer, primary_key=True)
    # Where the item came from ("dataset" now; web sources later) and its
    # identifier within that source. Source-specific extras go in item_metadata.
    source_kind: Mapped[str] = mapped_column(String(50), default="dataset")
    source_item_id: Mapped[str] = mapped_column(String(300))
    # Dataset-relative path now; may become a URL for web results.
    image_locator: Mapped[str | None] = mapped_column(String(1000))
    raw_score: Mapped[float | None] = mapped_column(Float)
    item_metadata: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)

    run: Mapped[SearchRun] = relationship(back_populates="results")
