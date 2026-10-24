# M01 — Persistent sessions and local images

Status: in progress (slices 1.1–1.4 implemented; acceptance checks pending, run by owner)  
Last edited: 2026-10-24  
Prerequisites: M00 accepted.  
Owner review: pending

[Overview](../../PROJECT_OVERVIEW.md) · [Milestone index](../../README.md)

This is an editable build plan. Implement one agreed slice at a time; stop at the milestone boundary for owner review. No task below has been completed by creating this document.

## Outcome

A session contains a reference image, textual search turns and saved ranked results. After restarting the app and PostgreSQL, the owner can reopen it and see the same history and images.

## Scope

Extend the existing UI with session selection and history. Add PostgreSQL persistence and app-managed image files. Preserve the working retrieval behaviour. No LLM conversation, web search or merchant evaluation is required.

## Build slices

### 1.1 Add persistence infrastructure

- [x] Add a local PostgreSQL setup, preferably Compose with a named persistent volume. (`compose.yaml`, volume `scanger_scanger_pgdata`, port 5433.)
- [x] Keep connection settings in environment configuration; provide a secret-free example. (`.env.example`.)
- [x] Add SQLAlchemy models and Alembic migrations for Session, Asset, Turn, SearchRun and SearchResult.
- [x] Use stable IDs, timestamps, foreign keys and unique per-session turn/per-run result ordering.
- [x] Store configuration as versioned structured data; do not store arbitrary Python objects. (`configuration_version` + JSONB.)
- [x] Document start/stop, migrations and backup. Avoid destructive volume-reset commands in routine startup instructions. (`docs/persistence.md`; restore not yet tested.)

The database stores history and metadata. Preserve the baseline vector index; do not install pgvector just to save sessions.

### 1.2 Make image uploads durable

- [x] Decode and validate supported image formats with byte and dimension limits. (JPEG/PNG/WebP, 10 MiB, 4096 px per side.)
- [x] Copy upload bytes out of temporary frontend storage into DATA_ROOT. (The frontend posts Gradio's unmodified temp file, `image_mode=None`, to `POST /assets`; identical bytes reuse the existing asset.)
- [x] Store a generated relative storage key plus original filename, type, dimensions and hash.
- [x] Expose images by asset ID through controlled serving. (`GET /assets/{id}` in `scanger/api.py`.)
- [x] Reject absolute paths and traversal; never expose the whole filesystem as a static directory.
- [x] Define cleanup for a failed upload/database write and missing-file behaviour. (File removed on DB failure; orphans reported, never auto-deleted; missing file gives 404 `asset_file_missing`, row kept.)

Do not expect the browser to disclose the original filesystem path. Store the durable app-owned copy's location. If a native file-path import is added later, make it a separate deliberate feature.

### 1.3 Persist a complete search turn

- [x] Create/select/rename a session. (Titles are owner-entered.)
- [x] Show the effective reference and text before search. (Live "Will search" summary: mode, reference source, description, image weight.)
- [x] Save a turn and a pending run before inference.
- [x] Run retrieval using the existing adapter. (`scanger/retrieval.py` calls the unmodified VisualMatch API over HTTP.)
- [x] Commit ranked results and completed status together; store useful failure state on error.
- [x] Save dataset/model/index versions, search mode, result count and score semantics. (Version strings are constants in `scanger/retrieval.py` taken from the M00 handoff.)
- [x] Prevent repeated UI events from accidentally duplicating a turn. (Search button ignores clicks while pending; each draft carries a `client_request_id`, unique per session.)
- [x] Reconcile interrupted pending/running jobs on restart as interrupted or retryable. (Scanger API startup marks them `interrupted`; "Run again" retries.)

Each query is complete and explicit. Reusing an image is allowed if visible. A new text entry does not implicitly inherit all earlier constraints. A retry creates a new run linked to the same turn.

### 1.4 Add session history to the frontend

- [x] List sessions ordered by recent activity.
- [x] Open one session and display turns chronologically.
- [x] Show reference previews, prompts, run state and saved result grids. (Earlier runs of a turn are in collapsed sections.)
- [x] Restore results from the database without rerunning retrieval.
- [x] Display a placeholder for a missing image while preserving the record.
- [x] Keep session selection separate from in-memory framework state. (Only the open session ID is held in Gradio state; history is re-read from the API on every render.)

## Acceptance checks

1. Create two sessions with distinct images and prompts.
2. Search twice in one session and once in the other.
3. Restart frontend, backend and database without deleting its volume.
4. Reopen both; verify prompts, reference previews, order and results remain correct.
5. Rename or remove the originally selected source image outside DATA_ROOT; the stored preview still works.
6. Simulate retrieval failure; history contains a failed run with no fabricated results.
7. Try a malformed image and an invalid asset path; receive a controlled error.
8. Restore a database-plus-files backup to a different DATA_ROOT and verify relative references.
9. Verify rerun creates a separate run and preserves earlier results.

Automate the persistence round trip, invalid path handling and run failure transition. Use a small fixture retrieval adapter for these tests; avoid requiring a full model download in database tests.

## Questions to resolve

- Which minimal UI layout best fits the existing frontend?
- Should initial session titles be derived from the first prompt or owner-entered?
- How are dataset images referenced durably across index rebuilds?
- What upload limits fit actual reference images?
- Does the owner want deletion now, or can it wait? Define shared-asset cleanup before adding deletion.

## Handoff

The owner can use this as a persistent local search tool. M02 can assess quality without rebuilding the interface.

## Work log

| Date | Task/change | Evidence or result | Next action |
| --- | --- | --- | --- |
| 2026-10-23 | Initial plan drafted | Documentation only | Review scope before implementation |
| 2026-10-24 | Slice 1.1: Compose DB, config, models, initial migration `a15a2c540c2d` | Observed: `docker compose ps` healthy; `alembic upgrade head` created 5 tables; inserting an absolute `storage_key` was rejected by the CHECK constraint; `alembic_version` intact after `docker compose restart db`; `pg_dump` produced a 332-line dump with 6 tables | Owner review |
| 2026-10-24 | Slice 1.2: `scanger/assets.py`, `scanger/api.py`, `tests/` | Observed: `python -m pytest` 30 passed (valid formats, malformed/truncated/GIF/oversize rejection, DB-failure file cleanup, traversal and symlink rejection, moved DATA_ROOT, missing file, HTTP upload/fetch). `uvicorn scanger.api:app` on 8010 answered `/health` 200 and unknown asset 404 against the real DB. Not done: frontend upload wiring, real-browser preview | Owner review, then slice 1.3 |
| 2026-10-24 | Slices 1.3–1.4: migration `3377947419ef` (`turn.client_request_id`; unique constraints renamed to include all columns), `scanger/retrieval.py`, `catalogue.py`, `history.py`, API routes, `scanger/frontend.py` | Observed: `python -m pytest` 48 passed (fixture adapter; no model). `alembic check` reports no drift; downgrade/upgrade of the new revision works. Live smoke on a throwaway database against the running VisualMatch API: text, image and composed turns completed; a catalogue image used as reference returned itself at rank 1 with score 1.0; result and asset images served. Frontend on a throwaway port loaded the session list and created a session via its event API. Not verified: history rendering and upload in a real browser | Owner runs acceptance checks |

## Decisions and plan changes

| Date | Decision | Reason / alternatives | Consequence |
| --- | --- | --- | --- |
| 2026-10-24 | Own Compose project on host port 5433, container `scanger-db` | Port 5432 is used by another project's database, which must stay untouched | Scanger code connects via `DB_HOST`/`DB_PORT` |
| 2026-10-24 | Session titles are owner-entered | Owner request; no inference from prompts | `session.title` is required |
| 2026-10-24 | Upload limits: 10 MiB, 4096 px per side, JPEG/PNG/WebP | Owner accepted proposed defaults; configurable | Larger images are rejected with 413 |
| 2026-10-24 | No deletion for now | Owner decision | Shared-asset cleanup stays undefined until deletion is added |
| 2026-10-24 | Result items identified by `source_kind` + `source_item_id` + `image_locator` + JSONB metadata | Future web results will have different metadata | Dataset item ID is not assumed to be globally unique |
| 2026-10-24 | Scanger's own FastAPI app (`scanger/api.py`) rather than editing the gitignored upstream API | Upstream edits are not versioned | — |
| 2026-10-24 | Frontend → Scanger API → VisualMatch API (HTTP retrieval adapter) | Alternatives: frontend calling both APIs (persistence logic in the UI), or loading the model inside the Scanger API (couples torch to persistence). The chain keeps the frontend thin and upstream unmodified | Three processes; new Scanger frontend `scanger/frontend.py` on port 7861; upstream frontend still usable on 7860 |
| 2026-10-24 | Search mode derived from inputs (image, text or both) | One form instead of three tabs; mode is stored per run | Composed uses the image-weight slider |
| 2026-10-24 | Identical uploads reuse one asset; assets are shared and immutable | Avoids duplicate files when searching repeatedly with the same reference | Deletion (deferred) must check all referencing turns |
| 2026-10-24 | Result count fixed at 10 | The VisualMatch API hardcodes `top_k=10` | `result_limit` is recorded per run |

## Exit review

- [ ] Acceptance checks recorded with actual results.
- [ ] Known limitations and unresolved questions updated.
- [ ] Relevant overview decisions brought up to date.
- [ ] Owner reviewed outcome and selected the next step.

