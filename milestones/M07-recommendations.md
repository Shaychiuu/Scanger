# M07 — Recommendations, reports and operational refinement

Status: not started  
Last edited: 2026-10-23  
Prerequisites: M06 accepted.  
Owner review: pending

[Overview](../../PROJECT_OVERVIEW.md) · [Milestone index](../../README.md)

This is an editable build plan. Implement one agreed slice at a time; stop at the milestone boundary for owner review. No task below has been completed by creating this document.

## Outcome

Return a useful shortlist with links, visual tradeoffs, prices and inspectable evidence. Make repeated use convenient without weakening earlier uncertainty handling.

## Scope

Recommendation presentation, filtering, report snapshots and measured operational improvements. Still no checkout or automatic purchasing.

## Build slices

### 7.1 Define transparent selection

- [ ] Apply explicit must-have and delivery constraints before preference ranking.
- [ ] Rank remaining candidates by visual fit and user-selected tradeoffs.
- [ ] Show known item price and shipping separately; label incomplete totals.
- [ ] Keep original currencies and date any conversion.
- [ ] Separate “closest appearance,” “lower known cost” and “stronger evidence” where helpful.
- [ ] Include limited-evidence alternatives only with their limitations visible.

### 7.2 Produce an evidence-backed report

- [ ] Show reference, effective intent, candidate images and live links.
- [ ] Explain matching attributes and meaningful differences.
- [ ] Include sizes/variants, price observation time and stock uncertainty.
- [ ] Link merchant, review, delivery and dispatch claims to evidence.
- [ ] List unresolved questions and exclusions.
- [ ] Save a versioned report snapshot; reopening must not silently regenerate it.
- [ ] Export Markdown first if the owner wants an external report.

A generated narrative may summarize stored evidence but must not invent facts, ratings or source links. Use deterministic rendering if that is simpler and more reliable.

### 7.3 Refine reliability based on usage

- [ ] Add visible stage progress and cancellation where needed.
- [ ] Track provider calls, model usage, latency and estimated versus actual costs distinctly.
- [ ] Implement deliberate refresh of expired offers/evidence.
- [ ] Cache stable data and avoid repeating costly work unnecessarily.
- [ ] Verify backup and restore across database, assets and manifests.
- [ ] Add queues or other infrastructure only when observed workload warrants them.

## Acceptance checks

For an owner-chosen reference, produce a shortlist whose visual explanations and factual claims can be audited. Demonstrate a no-qualified-results case without fabricating alternatives that satisfy hard constraints.

Reopen an old report, show its observation date and run an explicit refresh that creates a new version. Handle stale stock, broken links and partial provider failure. Confirm the local-dataset workflow still works without external credentials.

## Questions to resolve

- What report length and number of candidates best support decisions?
- Which tradeoffs should the default ordering favour?
- When should the app prompt for a refresh?
- Is preference learning useful enough to warrant a new separately scoped milestone?

## Completion evidence

Record an end-to-end example and owner assessment. Further ideas belong in a new backlog or milestone; they are not automatically authorized by this roadmap.

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

