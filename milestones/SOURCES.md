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
| [SerpApi Image API](https://serpapi.com/image-api) | Direct image upload for Lens (500 KB, 10-minute ID); checked 2026-10-25 |
| [Google LLC v. SerpApi docket](https://www.courtlistener.com/docket/72059948/google-llc-v-serpapi-llc/) | Provider continuity risk; pending as of 2026-10-25 |
| [Google Custom Search JSON API](https://developers.google.com/custom-search/v1/overview) | Closed to new customers; ends 2027-01-01 |
| [Brave Search API](https://brave.com/search/api/) | Independent-index comparison for M04.1; $5 per 1,000 requests as of 2026-10-25 |
| [SerpApi Google Search API](https://serpapi.com/search-api) | Organic route: `q`, `gl`, `hl`, `google_domain`, `location`; `site:` supported; 1 h free cache |
| [SerpApi Google Shopping API](https://serpapi.com/google-shopping-api) | Shopping route: ~40 results, no pagination; `product_link` is a Google page, the shop URL needs a further `google_immersive_product` search; `small_business` filter |
| [SerpApi Account API](https://serpapi.com/account-api) | Free quota check; its body also contains the API key and account e-mail |
| [SerpApi status and error codes](https://serpapi.com/api-status-and-error-codes) | 401 key, 429 quota/throughput, 200 + `error` for empty results |
| [SerpApi pricing](https://serpapi.com/pricing) | Free plan 250 searches/month, 50/hour, checked 2026-10-26 |

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

