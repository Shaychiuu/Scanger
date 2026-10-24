# FashionCLIP experiment

An alternative embedding model for the same catalogue, to compare against the
SigLIP baseline by hand. Model: [patrickjohncyh/fashion-clip](https://github.com/patrickjohncyh/fashion-clip)
(Hugging Face `patrickjohncyh/fashion-clip`, MIT, ViT-B/32, 512-d), pinned to the
revision in `scanger/fashionclip.py`.

## Use it

```
# once: embed the 52,591 catalogue images (about 10 min on Apple MPS, resumable)
python -m scanger.build_fashionclip_index

# switch model in .env, then restart
VISUALMATCH_MODEL=fashionclip
python -m scanger.dev
```

Switch back with `VISUALMATCH_MODEL=siglip_vitb16`. Both indexes live side by
side in `upstream/visualmatch/embeddings/`, so nothing is rebuilt when switching.
Each run stores `model_name` and `index_version`, so FashionCLIP and SigLIP runs
stay distinguishable in history.

`python -m scanger.build_fashionclip_index --limit 256` embeds a few rows,
prints throughput and saves nothing.

## How it is wired

- `scanger/fashionclip.py`: encoder and search engine with the same interface as
  upstream's `SearchEngine` (text, image, composed).
- `scanger/visualmatch_server.py`: the unmodified upstream FastAPI app with
  `get_engine` wrapped. Only `VISUALMATCH_MODEL=fashionclip` is affected.
- `scanger/build_fashionclip_index.py`: builds `fashionclip.index` (flat inner
  product over unit vectors, like the baseline) and `fashionclip.index.json`
  provenance. It checks each row's `item_ID` against upstream's `metadata.json`.

## Things to know

- Scores are cosine similarities in a different embedding space. Do not compare
  them numerically with SigLIP scores; compare the rankings.
- Composed search mixes image and text vectors, as in the baseline. CLIP-style
  models have a modality gap, so the useful `alpha` may differ from SigLIP's.
- Gotcha (torch 2.12 on arm64 + transformers 5.x): weights loaded straight from
  the memory-mapped safetensors file give garbage/NaN on CPU. The loader copies
  each parameter into fresh memory to avoid it.
- Import `torch` before `faiss`, otherwise macOS segfaults (two OpenMP copies).
