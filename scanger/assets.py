"""Durable, validated image storage under DATA_ROOT.

Flow for an upload: validate the bytes -> write a temp file inside DATA_ROOT ->
atomically rename to its final name -> insert the Asset row and commit. If the
database write fails the file is removed again. A crash between the rename and
the commit can leave an orphan file; `find_orphan_files` reports those (it never
deletes anything).

Assets are immutable and shared: several turns may reference the same asset.

Client-supplied file names and content types are display metadata only. The
stored key, extension and MIME type are generated from the decoded image.
"""

import hashlib
import io
import os
import re
import uuid
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from PIL import Image
from sqlalchemy import select
from sqlalchemy.orm import Session as OrmSession

from scanger.config import UploadLimits
from scanger.models import Asset

UPLOAD_DIR = "uploads"

# Pillow format name -> (MIME type, file extension)
SUPPORTED_FORMATS = {
    "JPEG": ("image/jpeg", "jpg"),
    "PNG": ("image/png", "png"),
    "WEBP": ("image/webp", "webp"),
}


class AssetError(Exception):
    """Base class for expected, user-reportable asset problems."""


class InvalidImage(AssetError):
    pass


class UnsupportedImageFormat(InvalidImage):
    pass


class UploadTooLarge(AssetError):
    pass


class InvalidStorageKey(AssetError):
    pass


class AssetNotFound(AssetError):
    pass


class AssetFileMissing(AssetError):
    pass


@dataclass(frozen=True)
class ImageInfo:
    mime_type: str
    extension: str
    width: int
    height: int
    sha256: str
    byte_size: int


def inspect_image(data: bytes, limits: UploadLimits) -> ImageInfo:
    """Decode `data` fully and enforce format, byte and dimension limits."""
    if not data:
        raise InvalidImage("The upload is empty.")
    if len(data) > limits.max_bytes:
        raise UploadTooLarge(f"Image exceeds the {limits.max_bytes} byte limit.")
    try:
        with Image.open(io.BytesIO(data)) as image:
            fmt = image.format
            width, height = image.size
            if fmt not in SUPPORTED_FORMATS:
                raise UnsupportedImageFormat(
                    f"Unsupported image format: {fmt}. Use JPEG, PNG or WebP."
                )
            if max(width, height) > limits.max_dimension:
                raise UploadTooLarge(
                    f"Image is {width}x{height}; the limit is "
                    f"{limits.max_dimension} pixels per side."
                )
            image.load()  # catches truncated or corrupt data
    except AssetError:
        raise
    except Exception as exc:  # PIL raises many types, incl. DecompressionBombError
        raise InvalidImage("The file is not a readable image.") from exc
    mime_type, extension = SUPPORTED_FORMATS[fmt]
    return ImageInfo(
        mime_type=mime_type,
        extension=extension,
        width=width,
        height=height,
        sha256=hashlib.sha256(data).hexdigest(),
        byte_size=len(data),
    )


def resolve_storage_key(storage_key: str, data_root: Path) -> Path:
    """Map a relative storage key to a file path strictly inside `data_root`."""
    if not isinstance(storage_key, str) or not storage_key:
        raise InvalidStorageKey("Empty storage key.")
    if "\x00" in storage_key or "\\" in storage_key:
        raise InvalidStorageKey("Illegal character in storage key.")
    posix = PurePosixPath(storage_key)
    if posix.is_absolute() or re.match(r"^[A-Za-z]:", storage_key):
        raise InvalidStorageKey("Storage keys must be relative.")
    if any(part in ("", ".", "..") for part in storage_key.split("/")):
        raise InvalidStorageKey("Storage key contains a traversal segment.")
    root = data_root.resolve()
    path = (root / posix).resolve()  # resolves symlinks too
    if not path.is_relative_to(root):
        raise InvalidStorageKey("Storage key escapes DATA_ROOT.")
    return path


def _display_name(name: str | None) -> str | None:
    if not name:
        return None
    base = re.split(r"[\\/]", name)[-1]
    base = "".join(ch for ch in base if ch.isprintable()).strip()
    return base[:300] or None


def store_image(
    db: OrmSession,
    data: bytes,
    original_name: str | None,
    data_root: Path,
    limits: UploadLimits,
) -> Asset:
    """Validate and persist an uploaded image; return the committed Asset.

    Identical bytes reuse the existing asset (if its file is still present), so
    searching again with the same reference does not duplicate files.
    """
    info = inspect_image(data, limits)
    existing = db.scalars(
        select(Asset).where(Asset.sha256 == info.sha256).order_by(Asset.created_at)
    ).first()
    if existing is not None:
        try:
            if resolve_storage_key(existing.storage_key, data_root).is_file():
                return existing
        except InvalidStorageKey:
            pass

    asset_id = uuid.uuid4()
    storage_key = f"{UPLOAD_DIR}/{asset_id}.{info.extension}"
    final_path = resolve_storage_key(storage_key, data_root)
    final_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = final_path.with_name(f".{asset_id}.part")

    try:
        with open(temp_path, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, final_path)
    except BaseException:
        temp_path.unlink(missing_ok=True)
        final_path.unlink(missing_ok=True)
        raise

    asset = Asset(
        id=asset_id,
        storage_key=storage_key,
        original_name=_display_name(original_name),
        mime_type=info.mime_type,
        byte_size=info.byte_size,
        width=info.width,
        height=info.height,
        sha256=info.sha256,
    )
    try:
        db.add(asset)
        db.commit()
    except BaseException:
        db.rollback()
        final_path.unlink(missing_ok=True)
        raise
    return asset


def get_asset_file(db: OrmSession, asset_id: uuid.UUID, data_root: Path) -> tuple[Asset, Path]:
    """Return the Asset and its existing file, or raise a controlled error.

    A missing file raises AssetFileMissing; the database record is untouched.
    """
    asset = db.get(Asset, asset_id)
    if asset is None:
        raise AssetNotFound(f"No asset {asset_id}.")
    path = resolve_storage_key(asset.storage_key, data_root)
    if not path.is_file():
        raise AssetFileMissing(f"The file for asset {asset_id} is missing.")
    return asset, path


def find_orphan_files(db: OrmSession, data_root: Path) -> list[str]:
    """List files under uploads/ with no Asset row (including stray .part files)."""
    upload_dir = data_root.resolve() / UPLOAD_DIR
    if not upload_dir.is_dir():
        return []
    known = set(db.scalars(select(Asset.storage_key)))
    on_disk = {
        f"{UPLOAD_DIR}/{p.name}" for p in upload_dir.iterdir() if p.is_file()
    }
    return sorted(on_disk - known)
