# M05 — Extract and visually compare live products

Status: not started  
Last edited: 2026-10-23  
Prerequisites: M04 accepted.  
Owner review: pending

[Overview](../../PROJECT_OVERVIEW.md) · [Milestone index](../../README.md)

This is an editable build plan. Implement one agreed slice at a time; stop at the milestone boundary for owner review. No task below has been completed by creating this document.

## Outcome

Convert candidate URLs into actual product records and compare their product images with the reference. Move from search leads to inspectable product offers.

## Scope

Product-page extraction, variants, image retrieval, visual comparison and deduplication. No retailer safety conclusion yet.

## Build slices

### 5.1 Define candidate records and provenance

- [ ] Add merchant-domain, product, variant, offer, page-snapshot and extraction-run concepts as needed.
- [ ] Capture title, canonical URL, images, stated materials, selected variant, currency, price and stock.
- [ ] Store unknown values explicitly and preserve original currency.
- [ ] Attach source URL, observation time and supporting field evidence.
- [ ] Distinguish parent product from size/colour-specific availability.

### 5.2 Extract with minimal machinery

- [ ] Start with accessible HTML and structured product data.
- [ ] Compare extracted fields with the rendered product page on a small reference set.
- [ ] Add browser rendering only for pages that require it; assess Crawl4AI at this point.
- [ ] Apply bounded fetch size, timeouts, redirect checks and per-domain pacing.
- [ ] Reject local/private-network targets, including after redirect and DNS resolution.
- [ ] Respect access restrictions; record blocked pages without inventing data.
- [ ] Separate product-gallery images from logos, recommendations and decorative assets.

### 5.3 Compare and consolidate

- [ ] Reuse the retrieval adapter or optional visual comparison rubric on downloaded candidate images.
- [ ] Explain decisive visual differences, requested-attribute matches and unknowns.
- [ ] Deduplicate identical product imagery without assuming sellers are equally reliable.
- [ ] Preserve separate offers and variants for price comparison.
- [ ] Keep image embedding configuration consistent with its model/preprocessing.
- [ ] Cache immutable image embeddings and refresh mutable offer information separately.

Consider pgvector only if persistent candidate embeddings create a clear need. If adopted, write a migration plan, dimensions/model identity rules and a retrieval equivalence check. Otherwise retain the simpler index arrangement.

## Acceptance checks

Manually verify a small set of pages with different layouts and at least one variant-dependent price or stock case. Correctly handle an unavailable page, category page, ambiguous price and missing image.

The result grid links to actual products, shows source timestamps and separates verified extracted fields from provisional discovery metadata. A missing price remains missing. The owner can trace an image comparison to the exact candidate image.

## Questions to resolve

- Which fields are reliable across target retailers?
- How often must offers be refreshed?
- Is a rendered crawler necessary for enough sites to justify its cost?
- Are matches failing due to discovery or image comparison?

## Handoff

M06 receives product/offer identities and evidence-bearing source records. Do not label candidates “trusted” yet.

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

