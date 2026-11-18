"""FastAPI dependencies shared by the Scanger API's routers (tests override these)."""

from collections.abc import Iterator
from pathlib import Path

from sqlalchemy.orm import Session as OrmSession

from scanger.config import UploadLimits, data_root, upload_limits
from scanger.db import get_session_factory


def get_db() -> Iterator[OrmSession]:
    with get_session_factory()() as db:
        yield db


def get_data_root() -> Path:
    return data_root()


def get_limits() -> UploadLimits:
    return upload_limits()
