"""Environment configuration for Scanger's own code (not the upstream checkout)."""

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import URL

REPO_ROOT = Path(__file__).resolve().parent.parent

load_dotenv(REPO_ROOT / ".env")


@dataclass(frozen=True)
class UploadLimits:
    max_bytes: int = 10 * 1024 * 1024
    max_dimension: int = 4096  # pixels, per side


def upload_limits() -> UploadLimits:
    defaults = UploadLimits()
    return UploadLimits(
        max_bytes=int(os.environ.get("MAX_UPLOAD_BYTES", defaults.max_bytes)),
        max_dimension=int(os.environ.get("MAX_IMAGE_DIMENSION", defaults.max_dimension)),
    )


def _required(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"{name} is not set. Add it to .env (see .env.example).")
    return value


def database_url() -> URL:
    # URL.create escapes special characters in the password.
    return URL.create(
        "postgresql+psycopg",
        username=_required("DB_USER"),
        password=_required("DB_PW"),
        host=os.environ.get("DB_HOST", "127.0.0.1"),
        port=int(os.environ.get("DB_PORT", "5433")),
        database=_required("DB_NAME"),
    )


def visualmatch_api_url() -> str:
    return os.environ.get("VISUALMATCH_API_URL", "http://127.0.0.1:8001").rstrip("/")


def scanger_api_url() -> str:
    return os.environ.get("SCANGER_API_URL", "http://127.0.0.1:8010").rstrip("/")


def visualmatch_model() -> str | None:
    return os.environ.get("VISUALMATCH_MODEL") or None


def cursor_api_key() -> str | None:
    return os.environ.get("CURSOR_API_KEY", "").strip() or None


def interpret_model() -> str | None:
    return os.environ.get("INTERPRET_MODEL", "").strip() or None


def interpret_model_params() -> dict[str, str]:
    """Parse INTERPRET_MODEL_PARAMS, e.g. "thinking=false,effort=low"."""
    params = {}
    for item in os.environ.get("INTERPRET_MODEL_PARAMS", "").split(","):
        if not item.strip():
            continue
        key, sep, value = item.partition("=")
        if not sep or not key.strip() or not value.strip():
            raise RuntimeError(f"INTERPRET_MODEL_PARAMS entry {item!r} is not id=value.")
        params[key.strip()] = value.strip()
    return params


def data_root() -> Path:
    raw = Path(os.environ.get("DATA_ROOT", "./user-data")).expanduser()
    return (raw if raw.is_absolute() else REPO_ROOT / raw).resolve()
