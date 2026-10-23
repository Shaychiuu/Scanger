# Clothing Search — project overview

Version: 0.1  
Updated: 2026-10-23  
Implementation status: documentation only  
Current focus: M00, followed by M01 and M02  
Project owner: the user; development is hands-on and supervised

## 1. Purpose

Build a personal application running on localhost that helps its owner find clothing resembling reference images and a written description. The owner selects an image from their filesystem, describes desired similarities or changes, and explores visual matches. Sessions remain available after restarting the app.

The eventual application will discover real product offers across countries and languages, compare their appearance with the reference, and provide evidence about retailer reputation, item reviews, delivery and dispatch origin. It should help discover smaller manufacturers as well as major retailers. It should explain uncertainty and differences rather than promise that a seller is safe or a garment is an exact match.

The first useful product is deliberately narrower: **select image + enter text → retrieve similar images from a local dataset → inspect results → reopen the saved session later**.

## 2. Development approach

This is a sequence of supervised learning and implementation milestones. It is not a one-shot autonomous build or a multi-agent project. The owner writes code, reviews suggestions, experiments with the results and edits the plans.

For coding assistants:

- Read this overview and the active milestone before proposing changes.
- Work only on the requested task within that milestone.
- Explain assumptions and make changes small enough to inspect.
- Do not infer authorization to implement the entire roadmap.
- Do not spawn other agents or introduce autonomous orchestration.
- Keep running code simpler than this long-term design; do not scaffold every future feature.
- Update progress with evidence and unresolved problems, not optimistic completion claims.
- Leave the transition to the next milestone to the owner.

Documentation is a design proposal. Names and contracts below are suggested boundaries, not claims that those modules already exist.

## 3. Immediate scope and user experience

The owner starts the local app, opens a search session, selects one reference image and enters an optional description. A preview shows what was uploaded. The app returns a grid of ranked dataset images, with identifiers and retrieval metadata. The owner can refine the text and run another search in the same session.

The initial meaning of “conversation” is a chronological collection of user search turns and result sets. It does not require an LLM chatbot or generated assistant responses. In the first version, each turn contains a complete query; previous text is not silently concatenated. A reference may be reused from the prior turn, but the UI must show the effective image and prompt before submission.

The app should retain both the original turn and the new turn. Reopening a session displays the saved results rather than silently rerunning a model whose outputs may have changed.

## 4. Explicitly deferred work

The first three milestones do not include web searches, scraping retailers, Trustpilot lookup, shipping verification, purchasing, model training or hosted LLM calls. Initial downloads of code, model weights and the dataset are setup activities, not web-product discovery.

Also out of scope initially: public hosting, multiple users, authentication infrastructure, a custom React frontend, a distributed job queue, a vector-database migration and permanent user-preference learning.

An early result is a **dataset image**, not a purchasable product recommendation. UI wording must preserve that distinction.

## 5. Selected technology stack

| Area | Selected direction | When / rationale |
| --- | --- | --- |
| Development | Cursor IDE, Git and a project repository | Owner-supervised implementation; preserve upstream attribution |
| Starting point | VisualMatch | Reproduce first, then extend with small changes |
| Language | Python; exact version pinned after baseline compatibility check | Avoid choosing a version before checking dependencies and hardware |
| Frontend | Gradio, adapting the existing interface | Initial file upload, text entry, result grid and session selector |
| Backend | FastAPI | Separate UI actions, persistence and retrieval logic |
| Local retrieval | Preserve the upstream model/index path first; FAISS baseline | Avoid changing the retrieval backend while validating behaviour |
| Persistence | PostgreSQL | Sessions, turns, assets, runs, ranked results and feedback |
| Database access | SQLAlchemy + psycopg; Alembic migrations | Proposed additions for explicit models and schema evolution |
| Images | App-managed local files; PostgreSQL stores relative storage keys | Durable previews without storing large binaries in database rows |
| Local database setup | Docker Compose with a persistent volume | Proposed repeatable default; native PostgreSQL remains acceptable |
| Validation | pytest plus a small manually judged retrieval set | Test meaningful failure paths and user-visible outcomes |
| Hosted interpretation | Cursor Python SDK behind a narrow adapter | M03 onward; optional to local retrieval |
| Web discovery | Provider adapter; SerpApi is the initial candidate | M04; confirm endpoints, coverage, prices and privacy then |
| Extraction | HTTP/structured-data extraction first; Crawl4AI candidate for rendering | M05; only add browser machinery when necessary |
| Vector persistence | pgvector deferred | Adopt only if persistent web-candidate embeddings justify replacing or supplementing FAISS |

**PostgreSQL and FAISS serve different purposes here.** Database persistence does not require migrating image similarity search into PostgreSQL. PostgreSQL stores application state; the baseline index supplies nearest neighbours.

Do not pin imagined dependency versions. During M00 record a working environment and the upstream commit. Later add dependencies deliberately and retain a reproducible lock or equivalent pinned environment.

## 6. External components and what is verified

The VisualMatch README describes a Gradio/FastAPI application with text, image and composed search over DeepFashion In-Shop, using embedding retrieval and reranking. Its documented composed-query baseline combines image and text embeddings; that alone should not be assumed to understand negation or precise garment edits. See [VisualMatch](https://github.com/soham-k-sinha/visualmatch).

This project has not yet reproduced that application. The dataset, model weights and generated index must be obtained or built; do not assume they are bundled in Git. Inspect the pinned checkout, reuse permissions, dataset terms, entrypoints and available artifacts before adoption. The documented catalogue is a dataset baseline, not a live inventory.

Cursor's [Python SDK documentation](https://cursor.com/docs/sdk/python) describes local and cloud runtimes, image input and usage associated with Cursor billing. Use the local runtime if suitable, but hosted model inference is still remote. Verify account access, model compatibility and actual billed usage in M03. IDE use while coding and SDK use inside this application are separate activities.

[pgvector](https://github.com/pgvector/pgvector) supports similarity search in PostgreSQL; its existence does not make it necessary for M01. [FashionCLIP](https://github.com/patrickjohncyh/fashion-clip) is a potential later model experiment, not an additional required baseline. [Crawl4AI](https://github.com/unclecode/crawl4ai) is a later extraction candidate. See [sources and verification limits](docs/SOURCES.md).

## 7. End-to-end pipeline

| Stage | Responsibility | Initial implementation | Later implementation |
| --- | --- | --- | --- |
| Input | Collect reference and user intent | One image, optional text, session | Cropping, multiple references, size, budget and destination |
| Interpret | Represent the query | Existing embedding encoders; preserve raw text | Structured attributes, constraints, uncertainties and query expansion |
| Discover | Obtain candidates | Search the fixed local catalogue | Visual search, multilingual organic search and shopping results |
| Extract | Normalize candidate information | Map dataset IDs to image assets | Fetch product images, variants, price, stock, materials and provenance |
| Compare | Rank visual/semantic relevance | Existing retrieval scoring | Candidate image comparison and constraint-aware reranking |
| Verify | Gather evidence | No merchant claims | Merchant identity, reviews, delivery, dispatch and returns |
| Recommend | Explain tradeoffs | Dataset result grid and feedback | Shortlist with separately visible match, price and evidence dimensions |
| Persist | Make work resumable | Save sessions, turns, assets and results | Save searches, extraction snapshots, evidence and report versions |

These are logical responsibilities, not a mandate for one service or agent per stage.

## 8. Application boundaries

Keep the frontend thin. It submits a query and displays the state returned by the backend. The backend owns upload validation, session history, search execution and access to stored assets.

A small retrieval adapter should isolate upstream specifics. Its conceptual input is a query image, text, search mode, result count and configuration. Its output is an ordered list of stable catalogue IDs with scores and model/index metadata. The exact function signature should follow the inspected code.

PostgreSQL is the source of truth for saved history. FAISS and model files are separately versioned retrieval artifacts. Image storage is local and owned by the application. A future model adapter translates between the app's structured requests and the Cursor SDK; SDK conversation state must not become the only copy of user history.

Do not require hosted LLM credentials to open a session or run the local retrieval path.

## 9. Initial data model

The following is a proposal for M01; implement only the fields required for its acceptance criteria.

| Entity | Main fields | Purpose |
| --- | --- | --- |
| Session | id, title, created_at, updated_at | Reopen a sequence of searches |
| Asset | id, storage_key, original_name, MIME type, byte size, dimensions, hash | Resolve a durable local image safely |
| Turn | id, session_id, ordinal, prompt_text, reference_asset_id, created_at | Preserve the effective user request |
| SearchRun | id, turn_id, status, configuration, model/index/dataset versions, timestamps, error | Record execution and reproducibility |
| SearchResult | run_id, rank, catalogue_item_id, image locator, raw score, score kind | Preserve exactly what was returned |
| Feedback | result or run reference, judgement, reason, created_at | M02 labels and observations |

Use foreign keys and unique ordering constraints. A turn can have multiple runs for explicit retries; rerunning does not overwrite the old result set. Store failed runs with a useful status. Record whether lower or higher scores are better. Do not display raw similarity as a probability.

## 10. Local file handling

A browser upload generally supplies bytes and a filename, not a trustworthy original absolute path. On receipt, validate the image and copy it into an application-owned directory. Store a relative key such as uploads/<asset-id>.jpg under a configurable DATA_ROOT.

Serve previews through a controlled asset endpoint or the framework's restricted serving facility. The browser should not depend on file:// links or unrestricted access to the owner's filesystem. Reject traversal and absolute-path input. Preserve original names as display metadata, not as path authority.

The database and asset directory form one backup set. Moving DATA_ROOT should preserve relative keys. Dataset result locators should likewise be rooted under a configurable dataset location, with stable IDs and a dataset manifest. A missing asset should display a clear placeholder without destroying its session record.

Uploads, datasets, model weights, indexes, secrets and database volumes stay out of Git. Commit code, migrations, dependency metadata, manifests without private data, documentation and appropriate small test fixtures.

## 11. Retrieval quality

“Close enough” is a user judgement, not whatever score the model emits. M02 records a small benchmark representing actual desired garments and modifications. Assess whether the top results contain useful options and which attributes fail.

Separate an easy catalogue-image self-match check from external reference-photo tests. A self-match only verifies plumbing. External photos reveal background, pose and domain mismatch. Text edits need their own evaluation; a search can be visually close while ignoring “without a belt.”

Start with the baseline. Change one variable at a time. A new model or different preprocessing requires compatible index embeddings; never compare vectors from unrelated spaces. Keep model revision, preprocessing and index manifest together.

## 12. Future web and evidence design

Discovery returns leads, not verified products. Extraction must establish the product page, selected variant, source image and observation time. Deduplicate identical offers without losing distinct retailers or variants. Preserve native currency and missing price fields.

For each evidence claim retain source URL, retrieval timestamp, supporting excerpt, subject identity and evidence type. Seller assertions and independent corroboration remain distinguishable. Product reviews and retailer reviews are separate. Missing reviews are unknown, not a negative rating.

For the future EU requirement, capture destination support, actual dispatch origin, duties/tax wording and returns destination independently. “Ships to Europe” does not meet a no-customs preference by itself. Label uncertainty and policy conflicts; do not infer shipment origin from a country-code domain.

No synthetic overall trust percentage is required. Begin with explicit dimensions and user-controlled filters. Positive product reviews can be preferred or strictly required, with the consequence for small manufacturers visible.

## 13. Operational principles

Run on loopback by default. Keep secrets in environment configuration, not prompts or tracked files. Distinguish local inference from network-enabled operations in the UI. Hosted analysis or reverse-image search may transmit the reference outside the machine.

When web access arrives, treat page content as untrusted data, prevent access to private network/file targets, constrain redirects and response sizes, and limit retries. Do not give product-page text authority over shell commands or agent instructions.

Use bounded work with visible status, cancellation where practical and provider budgets. Add a queue only when the simple execution model demonstrably fails the owner's needs.

## 14. Milestone governance

Follow [the milestone index](README.md). M00–M02 establish the local product. M03 adds optional hosted reasoning. M04–M05 extend candidates to the web. M06–M07 add evidence and recommendations.

Each plan contains scope, build slices, acceptance checks, questions and a work log. Completion requires observed evidence and owner review. Future plans may be rewritten or postponed without harming the local product.

The next concrete action is to inspect and reproduce the upstream baseline on the owner's machine. Do not download a large dataset, choose GPU dependencies or assert compatibility without first checking that machine and the available artifacts.

