# M04 — Discover candidate product URLs

Status: in progress — experimental CLI built and first run against the live SerpApi account; Web discovery tab in the app (2026-10-26)  
Last edited: 2026-10-26  
Prerequisites: M02 accepted; M03 accepted if hosted query expansion is used.  
Owner review: pending

[Overview](../../PROJECT_OVERVIEW.md) · [Milestone index](../../README.md)

This is an editable build plan. Implement one agreed slice at a time; stop at the milestone boundary for owner review. No task below has been completed by creating this document.

## Outcome

Find candidate product URLs outside the dataset while keeping the local-search mode available. Demonstrate broad discovery before implementing merchant judgement.

## Scope

Provider requests and result normalization. No general crawler, retailer trust calculation or automatic purchasing. Discovery metadata is provisional, not verified product information.

M04 makes no requests to retailer pages or retailer image URLs. Only provider APIs are called; page and image fetching, with its network guard, starts in M05.

## Background notes

Search is not "the web". Each route reads a different dataset owned by very few companies:

- Organic results: a ranked index (Google, Brave, Bing; Microsoft retired its public Bing Search APIs in 2025).
- Shopping results: mostly merchant-submitted feeds (Google Merchant Center), targeted per country.
- Visual search: Google Lens, reachable through scraping APIs such as SerpApi.

Google's official full-web API is closed to new customers and ends 2027-01-01. Most "Google APIs" therefore scrape Google, and Google is suing SerpApi (pending as of 2026-10). Treat provider continuity as a risk and keep the adapter replaceable. Brave runs an independent index but has no shopping or reverse-image route.

Providers default to a US location and English unless country, language and location are set explicitly. Results are a small ranked sample that varies over time and location; they are never exhaustive.

Google Shopping results through SerpApi carry the merchant's name and a link to Google's own product page, not the shop's URL. Resolving the shop URL costs one more search per product (`google_immersive_product`). Organic results link to the page directly.

Common Crawl and Web Data Commons (schema.org Product extractions) are possible offline sources for discovering small-maker domains later. They are stale for prices and stock and are not part of M04.

## Experimental CLI (current state)

```
python -m scanger.discover IMAGE --text "fluffy hood instead of the fur collar"
python -m scanger.discover --queries my-queries.json        # no LLM
python -m scanger.discover --from-record 3fa2               # reuse a run's queries
python -m scanger.discover --replay 3fa2                    # offline, no searches spent
python -m scanger.discover --list
  options: --markets de-at,fr  --max-calls N  --no-modifiers  --no-sites  --plan-only  --yes
```

- Settings: `discovery.toml` (markets, budget, query steps, small-maker modifiers, site targets, platform list). Each run stores a copy.
- Key: `SERPAPI_API_KEY` in `.env`.
- Code: `scanger/serpapi.py` (provider adapter), `scanger/leads.py` (normalization, diversity), `scanger/localize.py` (per-language queries), `scanger/discover.py` (plan, run, records, CLI).
- Runs are saved in `DATA_ROOT/discovery/<id>/`:
  - `record.json`: settings, queries, plan, call outcomes, leads, summary.
  - `queries.json`: copy it, edit it, and pass it back with `--queries`. This is the correction loop.
  - `raw/`: SerpApi responses with the key removed.
- Replay rebuilds leads from `raw/` with the current code and settings, so normalization changes can be compared without spending searches.

Flow with an image: the image is re-encoded without metadata and interpreted by Cursor; a second, text-only Cursor call writes the queries for the other languages; then the plan is shown, the SerpApi quota is checked and you confirm before any search is sent.

## Web discovery tab (app)

`python -m scanger.dev`, then the **Web discovery** tab. It reads and writes the same run files as the CLI, so runs made in either show up in both.

| CLI | App |
| --- | --- |
| `IMAGE --text "..." --plan-only` | New web search → "From a reference image", description, **Plan searches**. Planning never sends anything to SerpApi; the plan, the quota left and **Run searches** follow. |
| `--markets`, `--max-calls`, `--no-modifiers`, `--no-sites` | Markets checkboxes, search budget slider, extra-search checkboxes (defaults from `discovery.toml`). |
| `--queries FILE.json` | "My own queries": a table with one row per language, or load a queries file. |
| `--from-record ID` | **New search with these queries** on any run: the form is prefilled and the new run links to the old one. |
| `--replay ID` | **Replay offline** on any run with saved responses: leads rebuilt with the current code and settings, without changing the run. |
| `--list` | The saved-runs list on the left (status, date, leads, first query). |
| Terminal output | **Show full log**: the CLI's text report, plus each saved SerpApi response. |

- A run page shows an overview (status, leads, distinct sources, searches done, markets), then the leads as scrollable cards: title link, shop and site, price (unverified, with the struck-out old price), rating, delivery, badges (route, platform kind, product/listing page, second-hand condition, no shop link) and how each lead was found (search number, route, market, query kind and text, result position, other searches that found it).
- Filters: text, route, market, platform kind, sort (rank, price, source), hide listing pages, only leads with a shop link, thumbnails on/off.
- Accordions: what was searched for (interpretation and queries), the search plan with each call's outcome, and the summary with new sources per search.
- Runs execute in a background thread of the Scanger API (`scanger/discovery/discovery_service.py`, routes in `scanger/app/discovery_api.py` under `/discovery`). The record is saved after each search, the page refreshes every 2 seconds while a run is going, and **Stop after this search** cancels the rest. One run at a time. When the API starts, a run left "running" is finished with the searches it completed; the unsent ones are recorded as not run.
- UI code: `scanger/app/discovery_ui.py` (Gradio tab), `scanger/app/discovery_view.py` (HTML rendering, filters, styles).

## Implementation assumptions to revise

1. **Interface:** the CLI and the app's Web discovery tab, on the same JSON run files under `DATA_ROOT`, not in PostgreSQL sessions. Storing runs with sessions (4.3) is still open.
2. **Provider:** SerpApi only, free plan (250 searches/month, 50/hour). No manual provider comparison yet; Brave is not integrated.
3. **No reverse-image search (Lens).** Nothing image-based is sent to SerpApi.
4. **Markets:** `en-gb`, `de-de`, `de-at`, `fr-fr`, `it-it`, following your note. SerpApi uses `gl=uk` for the United Kingdom. The UK (and `de-ch`, defined but not enabled) are outside the EU, so customs may apply. `en-ie` is defined as an EU English alternative. No city-level `location` is set, so SerpApi may use its proxy's location for some signals.
5. **Budget:** `max_calls = 20` per run, with a hard ceiling of 50 in code to guard against typos.
   - With 5 markets, the first four steps fill the budget: precise query on Shopping, precise organic, broad query plus modifier on organic, and broad query with `site:etsy.com` on organic. Broad Shopping and synonym steps are cut.
   - The free plan gives about 12 such runs a month.
6. **Queries:**
   - English queries come straight from the interpreter (`interpret-v2`), which is assumed to write English. Other languages come from a text-only `localize-v2` call that receives the interpretation (not the image, not "uncertain").
   - Both prompts ask for neutral retail terms where the image cannot establish a material ("puffer", not "down"; "fur collar", not "real fur"). The localizer is also asked for grammatical agreement and one term per feature. v1 produced "brauner gesteppter Daunenjacke Pelzkragen Schalkragen" in the first live run.
   - Markets of one language share its queries.
   - Each query is capped at 150 characters (longer ones are refused). The localization prompt asks for no search operators, but no code strips them, so hand-written queries in `--queries` files can use `site:` or `-word` on purpose.
7. **Small-maker modifiers:** one first-guess term per language (handmade, handgemacht, fait main, artigianale), appended to the broad query on the organic route only. Edit `[modifiers]`; `--no-modifiers` drops those steps.
8. **Site targets:** `etsy.com` only, organic route only (Google Shopping ignores `site:`).
9. **Shopping filter:** the `small_business` filter is available but off. It probably only works in some countries.
10. **Lead identity:**
    - The deduplication key is host without `www.` plus path without trailing slash plus sorted query, after removing tracking parameters. The removed parameters are a fixed list: `utm_*`, `gclid`, `fbclid`, `srsltid`, `ref`, `spm` and others in `leads.py`. Variant parameters such as `?variant=` are kept. `page` is left out of the key only, so page 2 of a listing merges into page 1.
    - Shopping leads without a shop URL are keyed by Google product ID plus merchant name.
    - SerpApi's Shopping `product_link` contains the search text unencoded (`q=braune Steppjacke`). Plain spaces in its query part are percent-encoded before the URL checks; any other whitespace is still rejected.
    - Organic prices are taken from the displayed text ("305,00 €"). SerpApi's parsed number dropped the decimal comma (30500) in the first live run.
11. **Diversity unit (`source_key`):** the registrable domain's label (zalando.de and zalando.fr both count as "zalando"), or the merchant name for Shopping leads without a URL.
    - On a marketplace, a seller counts separately only when the merchant name has a separator ("eBay - shop42").
    - Organic Etsy results have no seller name, so they all count as "etsy".
12. **Ordering:** results are interleaved round-robin across calls by result position, then soft-capped: 3 per source, 6 for a marketplace without a known seller. Leads over the cap move to the end and are never dropped. At most 10 leads per call are normalized; raw responses keep everything. The summary prints results returned versus checked, so the cut is visible (Shopping returns about 40 per call).
13. **Platform list and page hints** are a starter list in `discovery.toml`. The product-like / category-like hints are URL-path guesses, not page checks. A platform's optional `product_path` regex decides for its own pages: a match is product-like, any other page on that platform is category-like. Other sites use generic path patterns.
14. **Retries:** one retry on timeouts, network errors and server errors. SerpApi's one-hour cache normally makes a repeat free if the first attempt completed there. Bad key, no searches left and hourly limit stop the run; the remaining calls are recorded as `not_run`.
15. **Retention:**
    - Raw SerpApi responses and leads are kept locally indefinitely, with no automatic deletion. SerpApi's retention terms have not been reviewed.
    - Thumbnail URLs are stored only if SerpApi- or Google-hosted. The Scanger servers never fetch them; the app shows them by letting the browser load them from `serpapi.com` or `*.gstatic.com` (https only, no referrer), and "Show thumbnails" turns that off.
16. **Image to Cursor:** `discover` re-encodes the image without EXIF/XMP (removing GPS and camera data). The older `python -m scanger.interpret` probe still sends the original bytes; this is unchanged and open.

## How to get Etsy and similar platforms included

1. **Google Shopping already includes them** when sellers or the platform submit feeds. Etsy does, so Etsy items appear in Shopping results with merchant "Etsy" (no shop URL).
2. **`site:` queries** on the organic route. This is the default `with_sites` step, one search per market per site. Add more domains to `site_targets`, for example `notonthehighstreet.com` (UK). Each one costs a search per market.
3. **Small-maker vocabulary** in `[modifiers]` brings independent shops' own sites into organic results.
4. **The platform's own API** (later, a second provider): Etsy's Open API v3 is free with a registered app key. It searches active listings by keyword and returns structured shop and listing data, including shipping profiles. Check its terms (caching, attribution) before use. Vinted, Depop and similar second-hand platforms have no general public search API.

Being on Etsy is not the same as being a small maker: resellers and print-on-demand shops are common there too.

## Build slices

### 4.0 Define a discovery benchmark

Skipped by owner decision (2026-10-26): too formal for now; manual trial and error instead. The measures it named are still printed by the CLI.

- [ ] Choose 5–8 owner references, including at least one with a requested change (e.g. a different hood or collar).
- [ ] For each, list a few shops the owner expects or would want to see, including small makers.
- [x] Define the measures: relevant leads in the top results, distinct registrable domains, distinct sellers, share of the most frequent domain, new domains per additional query, and how many expected shops were found. *(Printed per run, except "expected shops found", which needs 4.0.)*

### 4.1 Prove one provider

The manual provider comparison was replaced by an owner decision: SerpApi free plan, text routes only.

- [ ] Run the benchmark manually through provider playgrounds before writing an adapter. *(Skipped with 4.0.)*
- [x] Set country and language explicitly on every request. *(Per market: `gl`, `hl`, `google_domain`.)*
- [x] Recheck current prices, quotas, caching and error behaviour. *(SerpApi docs, 2026-10-26; see SOURCES.md.)* Retention terms still open.
- [x] Implement a provider adapter and retain raw response references. *(`scanger/serpapi.py`; offline tests with a fake transport.)*
- [x] Test one request for each adopted search route (organic, shopping) on the live account. *(Run `191d4c1b`, 2026-10-26: 2 Shopping + 1 organic, de-de/de-at.)*
- [x] Record source, route, query, market, retrieval time and provider search ID per call.
- [ ] Lens and Lens with text `q`. *(Deferred, owner decision.)*

### 4.2 Build bounded query expansion

- [x] Represent each planned call as (query text, market, route).
- [x] Generate queries from the interpretation, with native retail vocabulary per language. *(`localize-v1`; not yet run on the account.)*
- [x] Include small-maker modifiers per language, adjustable in `discovery.toml` or with `--no-modifiers`.
- [x] Enforce a per-run call budget, a per-call lead limit and bounded retries. The free plan cannot overspend; set a spending cap with the provider before moving to a paid plan.
- [ ] Distinguish exact-image search, image plus text, and attribute-based text alternatives. *(Only text exists.)*
- [x] Deduplicate URLs while preserving provenance: tracking parameters and Google redirect wrappers removed, variant parameters kept, duplicates listed under "also found in".
- [ ] Group locale copies of the same product without merging distinct retailers. *(Partial: one site across country domains counts as one source; product-level grouping not done.)*
- [x] Make retailer diversity measurable: registrable domain via the Public Suffix List (offline snapshot), platform, seller where the merchant name shows it.
- [x] Interleave results across routes and markets; soft caps per source, higher for marketplaces without a known seller.
- [ ] Keep exact-image matches recognisable as possible image reuse. *(Needs Lens.)*

Do not require a review profile or EU-looking domain during discovery. Those filters can hide the small manufacturers this project aims to find.

### 4.3 Present leads and save the search

The CLI and the Web discovery tab cover these; session storage is not built.

- [x] Add an explicit local / web mode selector to the UI. *(Tabs "Local search" and "Web discovery".)*
- [x] Display candidate titles, links and provider-hosted thumbnails in the UI. *(Result text is HTML-escaped; links open in a new tab without a referrer.)*
- [x] Clean result text before display and storage; allow only public http/https links. *(Terminal escapes, bidi overrides and other control characters removed; links with credentials, IP hosts, local names or odd ports rejected and counted; punycode hosts flagged.)*
- [x] Label prices, availability and ratings from search results as unverified.
- [x] Mark non-product results rather than dropping them: platform kind (social, aggregator, second-hand, marketplace) and URL-path hints.
- [ ] Save the query plan and discovery results under the session. *(Saved as run files, not in PostgreSQL.)*
- [x] Show partial results, provider failure, budget cuts and cancellation (Ctrl-C; **Stop after this search** in the app).
- [x] Record which routes and markets were attempted and the calls spent.

## Data leaving the machine

- **Cursor** (only with IMAGE): the image re-encoded without metadata, plus the user text, go to the interpretation call. The localization call receives only the interpretation JSON. The CLI asks before sending; in the app, **Plan searches** in image mode sends them, and the form says so above the button.
- **SerpApi**, and through it Google: the query text, country, language and Google domain of each call, plus the API key. The CLI shows the plan and the remaining quota, and asks before sending; the app shows both and sends nothing until **Run searches**.
- **Google, from the browser** (app only, while "Show thumbnails" is on): the browser loads result thumbnails from `serpapi.com` / `*.gstatic.com`, which sees the browser's IP address and the thumbnail URL, but no referrer.
- **Nothing else.** The Scanger servers fetch no retailer page, image or thumbnail. Opening a lead is a user click to the retailer's site, without a referrer.
- **Key handling:** SerpApi requires the key as a URL parameter.
  - The key is never logged, stored or printed. Request errors are replaced by fixed messages because their text contains the URL.
  - Response bodies are scrubbed of the key. The Account API's reply also contains the account e-mail, so only its quota numbers are kept.
  - Redirects are refused, responses are capped at 8 MB, and environment proxies and `.netrc` are ignored.
- **If Lens is added later:** upload the image directly to the provider (SerpApi Image API, max 500 KB, ID expires after 10 minutes). Never expose the local app through a tunnel or public URL, and never pass a local file path.

Result titles, snippets and URLs are untrusted third-party content. No result text is sent to an LLM in this version; if it ever is, it is data, never instructions.

## Acceptance checks

Run a few owner-chosen references through the adopted provider. Obtain relevant leads from multiple registrable domains and sellers, demonstrate at least one non-English query, and report the printed diversity measures. Handle zero results, duplicates, budget exhaustion and API failure gracefully. Replay a saved discovery result without spending another API call.

Offline evidence so far (2026-10-26): the full test suite passes (237 tests, including fake-provider runs for completion, fatal quota errors, quota refusal, plan-only and replay, background runs with progress and stop, the discovery API routes, and escaping of hostile result text in the app).

Live evidence (2026-10-26, run `191d4c1b`, `--markets de --max-calls 3`): all 20 Shopping results were first rejected because of the unencoded spaces in `product_link`. After the fix, a replay of the same raw responses gives 28 leads from 20 sources: 20 from Shopping and 8 from organic. All 20 Shopping leads have only a Google product page. Most organic leads are category pages. Relevance has not been judged.

The owner judges coverage manually. "No results" must not imply exhaustive absence across the internet.

## Questions to resolve

- Markets: is `de-at` worth a fifth of the budget, or should Austria be checked occasionally with `--markets de-at`? Should `en-gb` stay, given customs for EU buyers?
- Do Shopping leads without a shop URL justify one extra search each (`google_immersive_product`), or should only selected leads be resolved?
- Is reverse-image search materially better than text expansion for these garments, per kind of request (exact item versus edited intent)?
- Does adding markets or small-maker modifiers add new relevant domains, or mainly regional marketplaces? (Read "new sources per call" in the summary.)
- How many calls per run remain worthwhile once new sources per call level off?
- What retention rules apply to provider responses?
- Should the `scanger.interpret` probe also strip image metadata before sending?

## Handoff

M05 receives a normalized candidate URL list with discovery provenance and diversity groupings. Merchant trust remains unassessed.

## Work log

| Date | Task/change | Evidence or result | Next action |
| --- | --- | --- | --- |
| 2026-10-23 | Initial plan drafted | Documentation only | Review scope before implementation |
| 2026-10-25 | Plan revised after discussion: benchmark slice, manual provider comparison, data-leaving-machine rules, diversity definition | Documentation only; provider facts checked online 2026-10-25 | Owner writes the 4.0 benchmark |
| 2026-10-26 | Experimental CLI: `serpapi.py`, `leads.py`, `localize.py`, `discover.py`, `discovery.toml`; `interpret.py` refactored (shared `run_prompt`); `assets.without_metadata`; `tldextract==5.4.0` | 153 tests pass offline; CLI smoke-tested with `--plan-only`, `--list`, `--replay` and a missing key; no live SerpApi or Cursor call made | Owner adds `SERPAPI_API_KEY`, runs one `--plan-only` and one small run (e.g. `--markets de --max-calls 3`) |
| 2026-10-26 | Fixes from the first live runs: Shopping `product_link` spaces encoded; organic price read from the displayed text; `page` left out of the dedup key; per-platform `product_path`; summary shows results returned/checked and rejection reasons; prompts `interpret-v2` / `localize-v2` | 176 tests pass; replay of `191d4c1b`: 9 leads become 28, 0 rejected, price "305,00 €" | Owner runs one new small image run to judge the v2 queries |
| 2026-10-26 | Web discovery tab: `discovery_service.py` (background runs, progress, stop, replay, log), `/discovery` API routes, `discovery_ui.py` / `discovery_view.py`; `alembic/env.py` uses `NullPool` so the test database can be dropped reliably | 237 tests pass; headless-browser walk-through against a fake SerpApi: plan, run with live progress and stop button, replay (28 leads), full log, filters, reuse queries, tab switching | Owner tries a real image run from the app |

## Decisions and plan changes

| Date | Decision | Reason / alternatives | Consequence |
| --- | --- | --- | --- |
| 2026-10-25 | Compare providers manually before building an adapter | Alternatives: SerpApi adapter directly; two adapters up front | Superseded 2026-10-26 |
| 2026-10-25 | Initial languages: English, German, French, Italian | Alternative: home market plus neighbours | Markets refined 2026-10-26 |
| 2026-10-25 | About 20 provider calls per search while experimenting | Alternatives: ~5 calls; up to ~$1 | Query plan must choose among queries, markets and routes |
| 2026-10-25 | Provider-hosted thumbnails only; no retailer fetches in M04 | Alternatives: guarded backend proxy; no thumbnails | SSRF guard stays in M05 |
| 2026-10-26 | Skip the 4.0 benchmark and the manual provider comparison; SerpApi free plan, text routes only, no Lens | Owner: get a working version for trial and error first | Diversity measures printed per run; provider choice unproven |
| 2026-10-26 | CLI with JSON run files before UI/session integration | Fast trial and error, free replay; UI would also need the interpreter in the app | 4.3 UI and PostgreSQL storage remain open |
| 2026-10-26 | Markets as language + country pairs: en-gb, de-de, de-at, fr-fr, it-it | Owner note: GB; DE and AT; FR | Queries shared per language; 5 markets fill the budget in 4 steps |
| 2026-10-26 | Separate text-only localization call | Alternative: extend the interpretation prompt; that would resend the image to add a language | Two Cursor calls per image run |
| 2026-10-26 | Web discovery in the app on the CLI's run files, executed by the Scanger API in a background thread | Alternatives: PostgreSQL sessions first; running searches in the Gradio process | CLI and app share runs; one run at a time, single API process; session storage still open |
| 2026-10-26 | Thumbnails loaded by the browser straight from provider hosts, no referrer, with an off switch | Alternatives: backend proxy (a server-side fetch, kept for M05's SSRF guard); no thumbnails | Google sees the browser's IP address for thumbnails |

## Exit review

- [ ] Acceptance checks recorded with actual results.
- [ ] Known limitations and unresolved questions updated.
- [ ] Relevant overview decisions brought up to date.
- [ ] Owner reviewed outcome and selected the next step.
