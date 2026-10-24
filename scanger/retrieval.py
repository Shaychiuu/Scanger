"""Retrieval adapter: the only place that knows how VisualMatch is called.

The Scanger API calls the (unmodified) VisualMatch API over HTTP. Tests use a
fixture adapter with the same interface, so no model is needed for them.
"""

from dataclasses import dataclass, field
from typing import Any, Protocol

import requests

# Recorded on every run. Values come from the M00 handoff; update them when the
# index, model or dataset changes so old runs stay distinguishable.
VISUALMATCH_COMMIT = "941c69fa7d82c7fd5f570ad7392833b8d0b83791"
INDEX_VERSIONS = {
    "siglip_vitb16": "siglip_vitb16.index@hf-space:Sks123212/visualmatch@3be2e6250a4d07f84900a265c65769625b000327",
}
DATASET_VERSION = "Marqo/deepfashion-inshop@886fbe26ceac0b2bc8195d606e3fde641e7157f8"
DATASET_LOCATOR_PREFIX = "deepfashion-inshop:data:"
# The VisualMatch API hardcodes top_k=10.
VISUALMATCH_RESULT_LIMIT = 10


class RetrievalError(Exception):
    """Retrieval failed; the message is stored on the run and shown to the user."""


@dataclass(frozen=True)
class QueryImage:
    data: bytes
    mime_type: str
    filename: str


@dataclass(frozen=True)
class RetrievedItem:
    source_kind: str
    source_item_id: str
    image_locator: str | None
    raw_score: float | None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AdapterInfo:
    backend: str
    model_name: str | None
    index_version: str | None
    dataset_version: str | None
    score_kind: str
    higher_is_better: bool
    result_limit: int


class RetrievalAdapter(Protocol):
    info: AdapterInfo

    def search(
        self, mode: str, text: str | None, image: QueryImage | None, alpha: float
    ) -> list[RetrievedItem]: ...


class VisualMatchHttpAdapter:
    def __init__(self, base_url: str, model_name: str | None, timeout: float = 300):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.info = AdapterInfo(
            backend=f"visualmatch-http@{VISUALMATCH_COMMIT[:12]}",
            model_name=model_name,
            index_version=INDEX_VERSIONS.get(model_name or ""),
            dataset_version=DATASET_VERSION,
            # IndexFlatIP over unit-normalised embeddings.
            score_kind="cosine_similarity",
            higher_is_better=True,
            result_limit=VISUALMATCH_RESULT_LIMIT,
        )

    def search(
        self, mode: str, text: str | None, image: QueryImage | None, alpha: float
    ) -> list[RetrievedItem]:
        data: dict[str, Any] = {}
        files = None
        if mode in ("text", "composed"):
            data["query"] = text
        if mode in ("image", "composed"):
            files = {"file": (image.filename, image.data, image.mime_type)}
        if mode == "composed":
            data["alpha"] = alpha

        url = f"{self.base_url}/search/{mode}"
        try:
            response = requests.post(url, data=data, files=files, timeout=self.timeout)
        except requests.ConnectionError as exc:
            raise RetrievalError(
                f"VisualMatch API is not reachable at {self.base_url}. Is it running?"
            ) from exc
        except requests.Timeout as exc:
            raise RetrievalError(f"VisualMatch API timed out after {self.timeout}s.") from exc

        if response.status_code != 200:
            try:
                detail = response.json().get("detail")
            except ValueError:
                detail = response.text[:500]
            raise RetrievalError(f"VisualMatch API returned {response.status_code}: {detail}")

        try:
            return [_to_item(row) for row in response.json()["results"]]
        except (ValueError, KeyError, TypeError) as exc:
            raise RetrievalError("VisualMatch API returned an unexpected response.") from exc


def _to_item(row: dict[str, Any]) -> RetrievedItem:
    index = int(row["index"])
    return RetrievedItem(
        source_kind="dataset",
        source_item_id=str(row["item_id"]),
        image_locator=f"{DATASET_LOCATOR_PREFIX}{index}",
        raw_score=float(row["score"]),
        metadata={
            "dataset": "Marqo/deepfashion-inshop",
            "dataset_index": index,
            "category1": row.get("category1"),
            "category2": row.get("category2"),
            "color": row.get("color"),
        },
    )
