"""FashionCLIP (patrickjohncyh/fashion-clip) as a drop-in VisualMatch search engine.

Same interface as upstream `src.search.SearchEngine` (text_search, image_search,
composed_search), so the VisualMatch API and the Scanger adapter are unchanged.
Select it with VISUALMATCH_MODEL=fashionclip after building its index:

    python -m scanger.build_fashionclip_index

torch / transformers / faiss are imported lazily so that importing the version
constants (used by scanger.retrieval and the tests) stays cheap.
"""

import json
import os
from pathlib import Path
from typing import TYPE_CHECKING

from scanger.config import REPO_ROOT

if TYPE_CHECKING:
    from PIL import Image

MODEL_NAME = "fashionclip"  # value of VISUALMATCH_MODEL
MODEL_ID = "patrickjohncyh/fashion-clip"
# Pinned so the query encoder always matches the index. Rebuild the index if you change it.
MODEL_REVISION = "7e3ba62ce16b379a1ab479346b66f192e76f51b7"
DATASET_ID = "Marqo/deepfashion-inshop"
DATASET_REVISION = "886fbe26ceac0b2bc8195d606e3fde641e7157f8"

EMBEDDINGS_DIR = REPO_ROOT / "upstream" / "visualmatch" / "embeddings"
INDEX_PATH = EMBEDDINGS_DIR / "fashionclip.index"
METADATA_PATH = EMBEDDINGS_DIR / "metadata.json"  # shared with the SigLIP baseline: same row order

INDEX_VERSION = f"fashionclip.index@local:{MODEL_ID}@{MODEL_REVISION}"


def pick_device() -> str:
    import torch

    forced = os.environ.get("FASHIONCLIP_DEVICE")
    if forced:
        return forced
    if torch.cuda.is_available():
        return "cuda"
    if torch.backends.mps.is_available():
        return "mps"
    return "cpu"


class FashionClipEncoder:
    """Loads the model and turns images/text into unit-norm float32 vectors."""

    def __init__(self, device: str | None = None):
        import torch
        from transformers import CLIPModel, CLIPProcessor

        self.device = device or pick_device()
        model = CLIPModel.from_pretrained(MODEL_ID, revision=MODEL_REVISION)
        # transformers 5 memory-maps the safetensors, leaving weights at misaligned addresses.
        # On arm64 CPU, torch 2.12 then returns garbage (~1e20, then NaN) from matmuls.
        # Copying each parameter into fresh, aligned memory avoids it.
        for param in model.parameters():
            param.data = param.data.clone()
        self.model = model.to(self.device).eval()
        processor = CLIPProcessor.from_pretrained(MODEL_ID, revision=MODEL_REVISION)
        self.image_processor = processor.image_processor
        self.tokenizer = processor.tokenizer
        self._torch = torch

    @staticmethod
    def _features(output):
        # transformers 5 returns a ModelOutput whose pooler_output is the projected embedding.
        return output if hasattr(output, "norm") else output.pooler_output

    def _normalise(self, features):
        features = features / features.norm(dim=-1, keepdim=True)
        return features.cpu().numpy().astype("float32")

    def encode_images(self, images: "list[Image.Image]"):
        pixel_values = self.image_processor(
            [img.convert("RGB") for img in images], return_tensors="pt"
        )["pixel_values"].to(self.device)
        with self._torch.no_grad():
            return self._normalise(self._features(self.model.get_image_features(pixel_values=pixel_values)))

    def encode_texts(self, texts: list[str]):
        tokens = self.tokenizer(
            texts, padding=True, truncation=True, max_length=77, return_tensors="pt"
        ).to(self.device)
        with self._torch.no_grad():
            features = self.model.get_text_features(
                input_ids=tokens["input_ids"], attention_mask=tokens["attention_mask"]
            )
            return self._normalise(self._features(features))


class FashionClipEngine:
    def __init__(
        self,
        index_path: Path = INDEX_PATH,
        metadata_path: Path = METADATA_PATH,
        device: str | None = None,
    ):
        if not Path(index_path).exists():
            raise FileNotFoundError(
                f"{index_path} does not exist. Build it first: python -m scanger.build_fashionclip_index"
            )
        # torch first, then faiss: the reverse order segfaults on macOS (two copies of OpenMP).
        self.encoder = FashionClipEncoder(device)
        import faiss

        print(f"Loading FAISS index from: {index_path}")
        self.index = faiss.read_index(str(index_path))
        with open(metadata_path) as f:
            self.metadata = json.load(f)
        if self.index.ntotal != len(self.metadata):
            raise RuntimeError(
                f"Index has {self.index.ntotal} vectors but metadata has {len(self.metadata)} rows."
            )
        print(f"FashionCLIP ready on {self.encoder.device}")

    def _search_index(self, query_vector, top_k: int = 10):
        scores, indices = self.index.search(query_vector.astype("float32").reshape(1, -1), top_k)
        results = []
        for score, idx in zip(scores[0], indices[0]):
            result = self.metadata[idx].copy()
            result["score"] = float(score)
            results.append(result)
        return results

    def text_search(self, query: str, top_k: int = 10):
        return self._search_index(self.encoder.encode_texts([query])[0], top_k)

    def image_search(self, image: "Image.Image", top_k: int = 10):
        return self._search_index(self.encoder.encode_images([image])[0], top_k)

    def composed_search(self, image: "Image.Image", text: str, alpha: float = 0.5, top_k: int = 10):
        image_vec = self.encoder.encode_images([image])[0]
        text_vec = self.encoder.encode_texts([text])[0]
        composed = alpha * image_vec + (1 - alpha) * text_vec
        composed /= (composed @ composed) ** 0.5
        return self._search_index(composed, top_k)
