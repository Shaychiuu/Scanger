"""HTTP helpers for the Gradio pages. The frontend talks only to the Scanger API."""

import io
from datetime import datetime
from functools import lru_cache

import requests
from PIL import Image, ImageDraw

from scanger.config import scanger_api_url

API_URL = scanger_api_url()
HTTP = requests.Session()


class ApiError(Exception):
    pass


def call(method: str, path: str, timeout: float = 30, **kwargs) -> dict | list:
    try:
        response = HTTP.request(method, f"{API_URL}{path}", timeout=timeout, **kwargs)
    except requests.RequestException as exc:
        raise ApiError(f"Scanger API is not reachable at {API_URL}. Is it running?") from exc
    if response.status_code >= 400:
        try:
            detail = response.json().get("detail")
        except ValueError:
            detail = response.text[:300]
        raise ApiError(f"{detail}")
    return response.json()


@lru_cache(maxsize=1024)
def _image_bytes(path: str) -> bytes:
    # Stored assets and saved results are immutable, so caching is safe.
    # Failures raise and are therefore not cached.
    response = HTTP.get(f"{API_URL}{path}", timeout=30)
    response.raise_for_status()
    return response.content


def placeholder(text: str = "Image missing") -> Image.Image:
    image = Image.new("RGB", (256, 256), (225, 225, 225))
    ImageDraw.Draw(image).text((70, 120), text, fill=(90, 90, 90))
    return image


def fetch_image(path: str | None) -> Image.Image:
    if not path:
        return placeholder()
    try:
        return Image.open(io.BytesIO(_image_bytes(path)))
    except Exception:
        return placeholder()


def local_time(iso: str) -> str:
    return datetime.fromisoformat(iso).astimezone().strftime("%Y-%m-%d %H:%M")
