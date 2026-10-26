import io
import uuid

import pytest
from PIL import Image
from sqlalchemy import select

from scanger import assets
from scanger.models import Asset


def make_image(fmt="PNG", size=(40, 30), color=(200, 30, 30)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, color).save(buffer, format=fmt)
    return buffer.getvalue()


# --- storing ---------------------------------------------------------------


def test_store_image_persists_file_and_row(db, data_root, limits):
    data = make_image("PNG")
    asset = assets.store_image(db, data, "../../evil/boots.png", data_root, limits)

    assert asset.storage_key == f"uploads/{asset.id}.png"
    assert asset.original_name == "boots.png"  # display only, path stripped
    assert (asset.mime_type, asset.width, asset.height) == ("image/png", 40, 30)
    assert asset.byte_size == len(data)
    assert (data_root / asset.storage_key).read_bytes() == data
    assert db.get(Asset, asset.id).sha256 == asset.sha256


@pytest.mark.parametrize(
    "fmt, mime, ext", [("JPEG", "image/jpeg", "jpg"), ("WEBP", "image/webp", "webp")]
)
def test_supported_formats_use_detected_type_not_filename(
    db, data_root, limits, fmt, mime, ext
):
    asset = assets.store_image(db, make_image(fmt), "photo.png", data_root, limits)
    assert asset.mime_type == mime
    assert asset.storage_key.endswith(f".{ext}")


@pytest.mark.parametrize(
    "data, error",
    [
        (b"", assets.InvalidImage),
        (b"not an image at all", assets.InvalidImage),
        (make_image("PNG", size=(200, 200))[:150], assets.InvalidImage),  # truncated
        (make_image("GIF"), assets.UnsupportedImageFormat),
        (make_image("PNG", size=(600, 10)), assets.UploadTooLarge),  # > 512 px
        (b"\x00" * 300_000, assets.UploadTooLarge),  # > 200 kB
    ],
)
def test_bad_uploads_are_rejected_without_side_effects(
    db, data_root, limits, data, error
):
    with pytest.raises(error):
        assets.store_image(db, data, "x.png", data_root, limits)
    assert db.scalars(select(Asset)).all() == []
    assert not [p for p in data_root.rglob("*") if p.is_file()]


def test_database_failure_removes_the_file(db, data_root, limits, monkeypatch):
    def boom():
        raise RuntimeError("database down")

    monkeypatch.setattr(db, "commit", boom)
    with pytest.raises(RuntimeError):
        assets.store_image(db, make_image(), "a.png", data_root, limits)
    assert list((data_root / "uploads").iterdir()) == []


def test_find_orphan_files_reports_but_does_not_delete(db, data_root, limits):
    asset = assets.store_image(db, make_image(), "a.png", data_root, limits)
    stray = data_root / "uploads" / ".crashed.part"
    stray.write_bytes(b"partial")

    assert assets.find_orphan_files(db, data_root) == ["uploads/.crashed.part"]
    assert stray.exists() and (data_root / asset.storage_key).exists()


# --- path safety -----------------------------------------------------------


@pytest.mark.parametrize(
    "key",
    [
        "",
        "/etc/passwd",
        "../secret.png",
        "uploads/../../secret.png",
        "uploads/./a.png",
        "uploads//a.png",
        "uploads\\a.png",
        "C:/Windows/a.png",
        "uploads/a\x00.png",
    ],
)
def test_resolve_storage_key_rejects_unsafe_keys(data_root, key):
    with pytest.raises(assets.InvalidStorageKey):
        assets.resolve_storage_key(key, data_root)


def test_resolve_storage_key_rejects_symlink_escape(tmp_path, data_root):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "x.png").write_bytes(b"x")
    (data_root / "uploads").mkdir(parents=True)
    (data_root / "uploads" / "link").symlink_to(outside)
    with pytest.raises(assets.InvalidStorageKey):
        assets.resolve_storage_key("uploads/link/x.png", data_root)


def test_relative_keys_survive_moving_data_root(db, data_root, limits, tmp_path):
    asset = assets.store_image(db, make_image(), "a.png", data_root, limits)
    moved = tmp_path / "moved"
    data_root.rename(moved)
    _, path = assets.get_asset_file(db, asset.id, moved)
    assert path == (moved / asset.storage_key).resolve()


# --- lookup ----------------------------------------------------------------


def test_get_asset_file_unknown_id(db, data_root):
    with pytest.raises(assets.AssetNotFound):
        assets.get_asset_file(db, uuid.uuid4(), data_root)


def test_missing_file_is_reported_and_record_is_preserved(db, data_root, limits):
    asset = assets.store_image(db, make_image(), "a.png", data_root, limits)
    (data_root / asset.storage_key).unlink()
    with pytest.raises(assets.AssetFileMissing):
        assets.get_asset_file(db, asset.id, data_root)
    assert db.get(Asset, asset.id) is not None


# --- HTTP ------------------------------------------------------------------


def test_upload_then_fetch_by_id(client):
    data = make_image("JPEG")
    response = client.post("/assets", files={"file": ("shirt.jpg", data, "image/jpeg")})
    assert response.status_code == 201
    body = response.json()
    assert body["mime_type"] == "image/jpeg" and body["original_name"] == "shirt.jpg"

    fetched = client.get(body["url"])
    assert fetched.status_code == 200
    assert fetched.content == data
    assert fetched.headers["content-type"] == "image/jpeg"
    assert fetched.headers["x-content-type-options"] == "nosniff"


def test_upload_malformed_image_is_a_controlled_error(client):
    response = client.post("/assets", files={"file": ("x.png", b"junk", "image/png")})
    assert response.status_code == 422
    assert "not a readable image" in response.json()["detail"]


def test_upload_too_large_is_413(client):
    big = make_image("PNG", size=(600, 10))
    response = client.post("/assets", files={"file": ("x.png", big, "image/png")})
    assert response.status_code == 413


@pytest.mark.parametrize("path", ["/assets/not-a-uuid", "/assets/..%2f..%2fetc%2fpasswd"])
def test_invalid_asset_path_is_a_controlled_error(client, path):
    assert client.get(path).status_code in (404, 422)


def test_unknown_and_missing_assets_have_distinct_errors(client, data_root):
    unknown = client.get(f"/assets/{uuid.uuid4()}")
    assert (unknown.status_code, unknown.json()["detail"]) == (404, "asset_not_found")

    data = make_image()
    created = client.post("/assets", files={"file": ("a.png", data, "image/png")}).json()
    for file in (data_root / "uploads").iterdir():
        file.unlink()
    missing = client.get(created["url"])
    assert (missing.status_code, missing.json()["detail"]) == (404, "asset_file_missing")


# --- sending to remote services --------------------------------------------


@pytest.mark.parametrize("fmt", ["JPEG", "PNG", "WEBP"])
def test_without_metadata_drops_exif_but_keeps_orientation(limits, fmt):
    exif = Image.Exif()
    exif[0x0112] = 6  # Orientation: display rotated 90 degrees
    exif[0x010F] = "SecretCam"  # camera make
    buffer = io.BytesIO()
    Image.new("RGB", (40, 30), (200, 30, 30)).save(buffer, format=fmt, exif=exif)
    data = buffer.getvalue()
    with Image.open(io.BytesIO(data)) as original:
        assert original.getexif().get(0x010F) == "SecretCam"

    cleaned = assets.without_metadata(data, assets.inspect_image(data, limits))
    with Image.open(io.BytesIO(cleaned)) as image:
        assert image.format == fmt
        assert dict(image.getexif()) == {}
        assert image.size == (30, 40)
