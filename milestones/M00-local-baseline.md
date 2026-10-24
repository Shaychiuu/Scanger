# M00 — Reproduce the local baseline

Status: Accepted  
Last edited: 2026-10-23  
Prerequisites: None. Start here.  

[Overview](../../PROJECT_OVERVIEW.md) · [Milestone index](../../README.md)

This is an editable build plan. Implement one agreed slice at a time; stop at the milestone boundary for owner review. No task below has been completed by creating this document.

## Outcome

Run the unmodified or minimally repaired baseline on the owner's machine and demonstrate an image search and an image-plus-text search. Establish what works before introducing persistence or changing retrieval.

## Scope

Use the upstream frontend and retrieval implementation. This phase has no app database changes, hosted model calls, retailer searches or custom scoring.

## Build slices


### 0.1 Establish the environment

- [ ] Create an isolated Python environment.
- [ ] Install the inspected dependencies and record necessary platform-specific adjustments.
- [ ] Keep changes minimal and preserve the original dependency inventory.
- [ ] Configure dataset/model/index paths without hardcoding the owner's home directory.
- [ ] Keep artifacts outside Git and record their source and revision.
- [x] Build or load a compatible index; check count, dimensions and ID-to-image mapping. (Loaded the published SigLIP index; see Handoff.)

### 0.2 Run and inspect

- [ ] Discover actual frontend/backend launch commands from the checkout.
- [ ] Bind services to localhost; do not enable a public sharing tunnel.

## Acceptance evidence

Eventually, The owner can select an image and enter text, obtain a non-empty result grid and identify the active model/index and dataset. The documented commands work from a fresh shell. Explain any subset, missing artifact, workaround or unsupported device.

Do not interpret successful retrieval as proof of useful matching quality; that is M02.

## Questions to resolve

- Is the dataset accessible under acceptable terms?
- Are usable prebuilt indexes available, or must they be built locally?
- Which upstream model/configuration is the simplest working baseline?
- Does the UI support the needed inputs as implemented?
- What minimum dependency changes were necessary?

## Handoff

Record working commands and configuration below. M01 may begin when the owner accepts the baseline.

| Item | Observed value |
| --- | --- |
| Checkout commit | `941c69fa7d82c7fd5f570ad7392833b8d0b83791` in `upstream/visualmatch` (detached HEAD, gitignored) |
| Environment | `.venv`, Homebrew Python 3.13.7. Installed: gradio 6.18.0, requests 2.34.2, pillow 12.2.0, uvicorn 0.54.0. `python-dotenv==1.2.2` is listed and required by `api/app.py`. Torch, OpenCLIP, and FAISS are not installed. |
| Dataset manifest | Checked |
| Model/index | `siglip_vitb16` (`ViT-B-16-SigLIP`, `webli`). Index and `metadata.json` downloaded 2026-10-24 from the author's HuggingFace Space `Sks123212/visualmatch` at revision `3be2e6250a4d07f84900a265c65769625b000327` into `upstream/visualmatch/embeddings/` (`search.py`'s default path; gitignored). `siglip_vitb16.index` sha256 `b5a6e44b…1f90dc` matches the published LFS oid. Selected with `VISUALMATCH_MODEL=siglip_vitb16` in the root `.env`. The CLIP indexes were not downloaded; the Space does not publish them. |
| Index validation | Observed: `IndexFlatIP`, dim 768, `index.ntotal` = metadata length = dataset length = 52,591. `metadata[i]["index"] == i` for every row. `item_id`, `category1`, `category2` and `color` agree with the cached `Marqo/deepfashion-inshop` row at the same position for all 52,591 rows (0 mismatches). First 2,000 stored vectors are unit-norm. |
| Search check | Observed on a throwaway instance (port 8002): `/search/image` with catalogue images 0, 1234 and 40000 returned each as rank 1 with score 1.0, so the ID-to-image mapping works. `/search/text` ("black dress") returned dresses. `/search/composed` returned 200. This verifies the plumbing only, not matching quality (M02). First request loads the model (about 12 s plus a one-off weight download). |
| Dependency gap | `transformers` is missing from the VisualMatch freeze, and SigLIP's tokenizer needs it. Without it, searches return 503 "No module named 'transformers'". Installed `transformers==5.20.2` and added it to `requirements.txt`. No existing package changed. |
| Backend launch command | `uvicorn api.app:app --host 127.0.0.1 --port 8001 --reload` from `upstream/visualmatch`, using Scanger `.venv`. Stays up. `GET /health` returned `{"status":"ok","engine_loaded":false}`. `POST /search/text` returned 503 because torch is not installed; the process kept listening. Local repair: `api/app.py` loads `SearchEngine` on the first search, not at import. |
| Frontend launch command | `python frontend/app.py` boots up the frontend at http://127.0.0.1:7860 |
