# Sources and verification notes

Reviewed: 2026-10-23.

These documents distinguish external descriptions from proposed architecture. Documentation was reviewed online; repositories were not installed, dependencies resolved, datasets downloaded or code executed. No upstream commit has yet been pinned.

## Primary references

| Source | Role |
| --- | --- |
| [VisualMatch repository](https://github.com/soham-k-sinha/visualmatch) | Intended baseline and upstream documentation |
| [VisualMatch README](https://github.com/soham-k-sinha/visualmatch/blob/main/README.md) | Setup guidance to verify against a pinned checkout |
| [VisualMatch requirements](https://github.com/soham-k-sinha/visualmatch/blob/main/requirements.txt) | Dependency inventory to inspect, not an environment tested here |
| [Cursor Python SDK](https://cursor.com/docs/sdk/python) | Runtime, authentication, image input and billing reference |
| [pgvector](https://github.com/pgvector/pgvector) | Optional future vector storage |
| [FashionCLIP](https://github.com/patrickjohncyh/fashion-clip) | Optional retrieval experiment |
| [Crawl4AI](https://github.com/unclecode/crawl4ai) | Candidate later extraction component |
| [SerpApi Lens](https://serpapi.com/google-lens-api) | Candidate visual discovery integration; revalidate at M04 |

## Interpretation of this research

Gradio and FastAPI are selected to minimize divergence from the documented baseline. PostgreSQL, SQLAlchemy, Alembic, managed file storage and session persistence are proposed additions; they are not asserted to be existing VisualMatch features.

The baseline catalogue size and upstream benchmark claims are not acceptance targets for this project. The owner should establish accessible data, local performance and meaningful personal evaluation criteria.

A GitHub repository being public does not alone establish permission to copy or redistribute its contents. Verify code licensing and model/dataset terms separately in M00. An external frontend directory view could not be fetched during this documentation pass, so exact UI wiring and entrypoints require checkout inspection.

SDK availability and pricing can change. M03 must test the owner's account and record the installed version. Model names in vendor examples should not become unexamined project defaults.

## Decisions made for this project

- Extend the baseline UI before considering a replacement.
- Add PostgreSQL for application history, while preserving the initial vector index.
- Store image files under a configurable local root with database references.
- Complete local usefulness and evaluation before adding hosted reasoning or web work.
- Keep all future integrations replaceable.
- Prefer provenance and explicit unknowns over an unexplained trust score.

## Record at implementation time

| Item | Value |
| --- | --- |
| Upstream commit | Not yet selected |
| Code license checked | Pending |
| Dataset source/revision and use terms | Pending |
| Model/checkpoint/revision and use terms | Pending |
| Python and dependency environment | Pending |
| Hardware and index-build requirements | Pending |
| Working launch commands | Pending |
| SDK account/billing verification | Deferred to M03 |

