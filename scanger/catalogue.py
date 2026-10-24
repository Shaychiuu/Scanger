"""Image lookup for saved dataset results.

Results are stored with a stable `item_id` plus a locator holding the dataset
position. The position is a fast path; if the row there no longer carries the
same item_id (dataset changed), the item is looked up by item_id instead.
"""

import io
import threading

from PIL import Image

from scanger.retrieval import DATASET_LOCATOR_PREFIX

HF_DATASET = "Marqo/deepfashion-inshop"
HF_SPLIT = "data"
MIME_TYPES = {"JPEG": "image/jpeg", "PNG": "image/png", "WEBP": "image/webp"}

_lock = threading.Lock()
_dataset = None
_index_by_item_id: dict[str, int] | None = None


class CatalogueImageUnavailable(Exception):
    pass


def _get_dataset():
    global _dataset
    with _lock:
        if _dataset is None:
            from datasets import Image as ImageFeature
            from datasets import load_dataset

            # decode=False keeps the original encoded bytes.
            _dataset = load_dataset(HF_DATASET, split=HF_SPLIT).cast_column(
                "image", ImageFeature(decode=False)
            )
        return _dataset


def _find_by_item_id(item_id: str) -> int | None:
    global _index_by_item_id
    dataset = _get_dataset()
    with _lock:
        if _index_by_item_id is None:
            _index_by_item_id = {v: i for i, v in enumerate(dataset["item_ID"])}
        return _index_by_item_id.get(item_id)


def load_dataset_image(locator: str | None, item_id: str) -> tuple[bytes, str]:
    """Return (image bytes, MIME type) for a saved dataset result."""
    dataset = _get_dataset()
    index = None
    if locator and locator.startswith(DATASET_LOCATOR_PREFIX):
        try:
            index = int(locator.removeprefix(DATASET_LOCATOR_PREFIX))
        except ValueError:
            index = None
    if index is None or not (0 <= index < len(dataset)) or dataset[index]["item_ID"] != item_id:
        index = _find_by_item_id(item_id)
    if index is None:
        raise CatalogueImageUnavailable(f"Dataset item {item_id} not found.")

    data = dataset[index]["image"]["bytes"]
    if not data:
        raise CatalogueImageUnavailable(f"Dataset item {item_id} has no image bytes.")
    with Image.open(io.BytesIO(data)) as image:
        mime_type = MIME_TYPES.get(image.format)
    if mime_type is None:
        raise CatalogueImageUnavailable(f"Dataset item {item_id} has an unknown image type.")
    return data, mime_type
