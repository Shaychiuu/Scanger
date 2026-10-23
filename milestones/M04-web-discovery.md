# M04 — Discover candidate product URLs

Status: not started  
Last edited: 2026-10-23  
Prerequisites: M02 accepted; M03 accepted if hosted query expansion is used.  
Owner review: pending

[Overview](../../PROJECT_OVERVIEW.md) · [Milestone index](../../README.md)

This is an editable build plan. Implement one agreed slice at a time; stop at the milestone boundary for owner review. No task below has been completed by creating this document.

## Outcome

Find candidate product URLs outside the dataset while keeping the local-search mode available. Demonstrate broad discovery before implementing merchant judgement.

## Scope

Provider requests and result normalization. No general crawler, retailer trust calculation or automatic purchasing. Discovery metadata is provisional, not verified product information.

## Build slices

### 4.1 Select and prove one provider

- [ ] Recheck current visual, organic and shopping API capabilities.
- [ ] Compare access, prices, geographical coverage and reference-image handling.
- [ ] Choose one provider for the first integration; SerpApi is a candidate, not a fixed dependency.
- [ ] Implement a provider adapter and retain raw response references as permitted.
- [ ] Test one request for each adopted search route.
- [ ] Record source, query, locale, retrieval time and provider request ID.

### 4.2 Build bounded query expansion

- [ ] Generate a small query set from the reference interpretation and user text.
- [ ] Keep a configurable limit on queries, returned candidates and retries.
- [ ] Include multilingual organic queries to find smaller manufacturers.
- [ ] Distinguish exact-image search from attribute-based alternatives.
- [ ] Deduplicate URLs while preserving source/query provenance.
- [ ] Keep retailer diversity visible; avoid returning only one large marketplace.

Do not require a review profile or EU-looking domain during discovery. Those filters can hide the small manufacturers this project aims to find.

### 4.3 Present leads and save the search

- [ ] Add an explicit local / web mode selector.
- [ ] Display candidate titles, links and thumbnails if permitted.
- [ ] Label prices, availability and ratings from search results as unverified.
- [ ] Save the query plan and discovery results under the session.
- [ ] Show partial results, provider failure and budget exhaustion.
- [ ] Record which routes/languages were attempted.

If visual search requires a remote image upload or reachable URL, document that data flow. Never pass a local filesystem path as if a remote provider can access it.

## Acceptance checks

For a small set of owner-chosen references, obtain relevant leads from multiple domains and demonstrate at least one multilingual query. Handle zero results, duplicates and API failure gracefully. Replay a saved discovery result without spending another API call.

The owner judges coverage manually. “No results” must not imply exhaustive absence across the internet.

## Questions to resolve

- Which countries/languages should receive the initial query budget?
- Is reverse-image search materially better than text expansion for these garments?
- How many discovery calls are affordable per search?
- What retention rules apply to provider images and responses?

## Handoff

M05 receives a normalized candidate URL list with discovery provenance. Merchant trust remains unassessed.

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

