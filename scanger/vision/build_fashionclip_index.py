"""Embed the whole catalogue with FashionCLIP and write a FAISS index.

    python -m scanger.build_fashionclip_index            # build and save
    python -m scanger.build_fashionclip_index --limit 256  # throughput check, saves nothing

Rows follow the dataset order, which is the order of upstream's metadata.json
(checked row by row). Progress is checkpointed so an interrupted run resumes.
"""

import argparse
import json
import time
from datetime import datetime, timezone

import numpy as np

from scanger.fashionclip import (
    DATASET_ID,
    DATASET_REVISION,
    EMBEDDINGS_DIR,
    INDEX_PATH,
    INDEX_VERSION,
    METADATA_PATH,
    MODEL_ID,
    MODEL_REVISION,
    FashionClipEncoder,
)

CHECKPOINT = EMBEDDINGS_DIR / "fashionclip.partial.npy"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument("--limit", type=int, help="only embed this many rows, report speed, save nothing")
    parser.add_argument("--device", help="cuda, mps or cpu (default: best available)")
    args = parser.parse_args()

    # faiss is imported only after the model is loaded: importing it before torch
    # segfaults on macOS (two copies of OpenMP).
    from datasets import load_dataset
    from tqdm import tqdm

    with open(METADATA_PATH) as f:
        metadata = json.load(f)
    ds = load_dataset(DATASET_ID, split="data", revision=DATASET_REVISION)
    if len(ds) != len(metadata):
        raise SystemExit(f"Dataset has {len(ds)} rows but {METADATA_PATH.name} has {len(metadata)}.")
    total = args.limit or len(ds)

    encoder = FashionClipEncoder(args.device)
    print(f"Embedding {total} images on {encoder.device} (batch size {args.batch_size})")

    chunks: list[np.ndarray] = []
    done = 0
    if not args.limit and CHECKPOINT.exists():
        saved = np.load(CHECKPOINT)
        chunks, done = [saved], len(saved)
        print(f"Resuming from checkpoint at row {done}")

    started = time.time()
    start_row = done
    for n, i in enumerate(tqdm(range(done, total, args.batch_size), initial=done // args.batch_size,
                               total=-(-total // args.batch_size))):
        end = min(i + args.batch_size, total)
        batch = ds[i:end]
        ids = batch["item_ID"]
        expected = [m["item_id"] for m in metadata[i:end]]
        if ids != expected:
            raise SystemExit(f"Dataset order differs from {METADATA_PATH.name} near row {i}.")
        chunks.append(encoder.encode_images(batch["image"]))
        if not args.limit and n % 100 == 99:
            np.save(CHECKPOINT, np.vstack(chunks))

    embeddings = np.vstack(chunks).astype("float32")
    rate = (len(embeddings) - start_row) / max(time.time() - started, 1e-9)
    print(f"Embedded {len(embeddings)} rows, {rate:.1f} images/s, shape {embeddings.shape}")
    if args.limit:
        print(f"Estimated full build: {len(ds) / rate / 60:.1f} min. Nothing saved (--limit).")
        return 0

    import faiss

    index = faiss.IndexFlatIP(embeddings.shape[1])  # same as the baseline: cosine over unit vectors
    index.add(embeddings)
    faiss.write_index(index, str(INDEX_PATH))
    INDEX_PATH.with_suffix(".index.json").write_text(
        json.dumps(
            {
                "index_version": INDEX_VERSION,
                "model": MODEL_ID,
                "model_revision": MODEL_REVISION,
                "dataset": DATASET_ID,
                "dataset_revision": DATASET_REVISION,
                "rows": int(index.ntotal),
                "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            },
            indent=2,
        )
        + "\n"
    )
    CHECKPOINT.unlink(missing_ok=True)
    print(f"Wrote {INDEX_PATH} ({index.ntotal} vectors)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
