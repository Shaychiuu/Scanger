# M06 — Merchant, review and delivery evidence

Status: not started  
Last edited: 2026-10-23  
Prerequisites: M05 accepted.  
Owner review: pending

[Overview](../../PROJECT_OVERVIEW.md) · [Milestone index](../../README.md)

This is an editable build plan. Implement one agreed slice at a time; stop at the milestone boundary for owner review. No task below has been completed by creating this document.

## Outcome

Add inspectable evidence for retailer reputation, product reviews and delivery suitability without collapsing missing data into a misleading score.

## Scope

Read-only research and evidence summaries. No automated purchase, account creation or messages to retailers. No guarantee of authenticity or customs-free delivery.

## Build slices

### 6.1 Define claim-level evidence

- [ ] Store claim type, subject, source URL, retrieval time, excerpt and source category.
- [ ] Separate seller assertions from independent corroboration.
- [ ] Preserve conflicts and distinguish not checked, unavailable, not found and contradicted.
- [ ] Set refresh policies by evidence type; retain historical observations.

### 6.2 Assess the exact merchant and item

- [ ] Resolve exact domain and legal entity before attaching review data.
- [ ] Collect available business identity and independently supported reputation information.
- [ ] Record review rating, count, recency and recurring complaint themes.
- [ ] Keep retailer reviews separate from reviews of the actual item/model.
- [ ] Do not transfer a parent-company or marketplace reputation to an unrelated seller.
- [ ] Evaluate Trustpilot access and terms at this milestone; do not assume unrestricted API access.
- [ ] Retain small manufacturers with sparse review coverage as “limited evidence.”

A registration number, HTTPS or payment logo alone does not prove a seller is legitimate. Do not generate a numerical scam probability without a defensible calibrated model.

### 6.3 Verify destination and dispatch independently

- [ ] Ask for the actual destination country; EU-wide wording is insufficient for all destinations.
- [ ] Record delivery availability, dispatch origin, shipping cost and timing.
- [ ] Capture taxes/duties wording and distinguish duties-paid imports from EU dispatch.
- [ ] Record return address/country, costs and exclusions.
- [ ] Apply policy evidence to the specific seller/offer where possible.
- [ ] Mark unresolved shipment origin or policy conflicts for owner confirmation.

Country-code domains, displayed currency and company address are not sufficient proof of where a particular item ships from. Avoid hardcoding customs-law thresholds; validate current authoritative guidance if the app gives legal/tax explanations.

### 6.4 Add transparent filtering

- [ ] Offer separate filters for visual relevance, delivery evidence and review requirements.
- [ ] Let the owner prefer positive item reviews or require them strictly.
- [ ] Explain why candidates are excluded.
- [ ] Keep a limited-evidence section so small businesses are not silently erased.
- [ ] Label ranking weights as owner preferences, not objective safety facts.

## Acceptance checks

Review cases representing strong evidence, sparse evidence, a wrong-domain review match, conflicting policies and unknown dispatch. Ensure unknowns remain unknown and every positive claim links to its support.

An excellent visual match cannot compensate for a failed hard delivery constraint. A seller claim cannot silently become independently verified fact.

## Questions to resolve

- Which evidence thresholds matter to the owner?
- Is EU dispatch mandatory, or are documented duties-paid imports acceptable?
- How should sparse-but-plausible manufacturers appear?
- Which review sources are practically accessible?

## Handoff

M07 receives separate evidence dimensions, exclusions and remaining questions, not a single opaque trust score.

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

