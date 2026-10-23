# M01 — Persistent sessions and local images

Status: not started  
Last edited: 2026-10-23  
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

- [ ] Add a local PostgreSQL setup, preferably Compose with a named persistent volume.
- [ ] Keep connection settings in environment configuration; provide a secret-free example.
- [ ] Add SQLAlchemy models and Alembic migrations for Session, Asset, Turn, SearchRun and SearchResult.
- [ ] Use stable IDs, timestamps, foreign keys and unique per-session turn/per-run result ordering.
- [ ] Store configuration as versioned structured data; do not store arbitrary Python objects.
- [ ] Document start/stop, migrations and backup. Avoid destructive volume-reset commands in routine startup instructions.

The database stores history and metadata. Preserve the baseline vector index; do not install pgvector just to save sessions.

### 1.2 Make image uploads durable

- [ ] Decode and validate supported image formats with byte and dimension limits.
- [ ] Copy upload bytes out of temporary frontend storage into DATA_ROOT.
- [ ] Store a generated relative storage key plus original filename, type, dimensions and hash.
- [ ] Expose images by asset ID through controlled serving.
- [ ] Reject absolute paths and traversal; never expose the whole filesystem as a static directory.
- [ ] Define cleanup for a failed upload/database write and missing-file behaviour.

Do not expect the browser to disclose the original filesystem path. Store the durable app-owned copy's location. If a native file-path import is added later, make it a separate deliberate feature.

### 1.3 Persist a complete search turn

- [ ] Create/select/rename a session.
- [ ] Show the effective reference and text before search.
- [ ] Save a turn and a pending run before inference.
- [ ] Run retrieval using the existing adapter.
- [ ] Commit ranked results and completed status together; store useful failure state on error.
- [ ] Save dataset/model/index versions, search mode, result count and score semantics.
- [ ] Prevent repeated UI events from accidentally duplicating a turn.
- [ ] Reconcile interrupted pending/running jobs on restart as interrupted or retryable.

Each query is complete and explicit. Reusing an image is allowed if visible. A new text entry does not implicitly inherit all earlier constraints. A retry creates a new run linked to the same turn.

### 1.4 Add session history to the frontend

- [ ] List sessions ordered by recent activity.
- [ ] Open one session and display turns chronologically.
- [ ] Show reference previews, prompts, run state and saved result grids.
- [ ] Restore results from the database without rerunning retrieval.
- [ ] Display a placeholder for a missing image while preserving the record.
- [ ] Keep session selection separate from in-memory framework state.

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

## Decisions and plan changes

| Date | Decision | Reason / alternatives | Consequence |
| --- | --- | --- | --- |
| Pending | — | — | — |

## Exit review

- [ ] Acceptance checks recorded with actual results.
- [ ] Known limitations and unresolved questions updated.
- [ ] Relevant overview decisions brought up to date.
- [ ] Owner reviewed outcome and selected the next step.

