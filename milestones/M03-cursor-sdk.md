# M03 — Optional Cursor SDK interpretation

Status: not started  
Last edited: 2026-10-23  
Prerequisites: M02 reviewed; local retrieval remains available independently.  
Owner review: pending

[Overview](../../PROJECT_OVERVIEW.md) · [Milestone index](../../README.md)

This is an editable build plan. Implement one agreed slice at a time; stop at the milestone boundary for owner review. No task below has been completed by creating this document.

## Outcome

Use Cursor's Python SDK for a bounded, optional image-and-text interpretation step. Later use the same adapter for shortlisted image comparisons. Validate the integration before depending on it for discovery.

## Scope

One provider adapter, explicit image transmission, structured outputs and usage recording. No web search tools, shell-driven shopping agent or unrestricted autonomous loop.

## Build slices

### 3.1 Verify the SDK independently

- [ ] Check current official documentation, installed version and account access.
- [ ] Select an available image-capable model deliberately.
- [ ] Send a harmless test image and verify the response.
- [ ] Check actual usage/billing and document account-specific limits.
- [ ] Establish an isolated workspace and narrow available tools/permissions.
- [ ] Record how secrets are configured and how remote processing is disclosed.

Use https://cursor.com/docs/sdk/python as the integration reference. Do not assume the current documentation examples or billing arrangements remain unchanged.

### 3.2 Define an app-owned interpretation contract

- [ ] Preserve raw user text and the original reference.
- [ ] Add garment category, observed visual attributes, requested changes, must-have attributes, exclusions and uncertainties.
- [ ] Distinguish user assertions, visually inferred properties and unknown material composition.
- [ ] Validate responses with a typed schema and a schema/prompt version.
- [ ] Show interpreted attributes for owner correction before using them as constraints.
- [ ] Save provider/model metadata, latency, usage when available and failure state.

The SDK response envelope being JSON does not guarantee that its generated content matches the application's schema. Parse and validate explicitly.

### 3.3 Connect interpretation to the local workflow

- [ ] Put SDK calls behind an optional adapter.
- [ ] Keep image-only/text-only baseline searches working without credentials.
- [ ] Use corrected attributes to construct a query while retaining the original request.
- [ ] Apply timeout and bounded retry behaviour.
- [ ] Test cancellation or interrupted-run handling.
- [ ] If justified, compare a small shortlist using a fixed attribute rubric.

Do not treat an LLM judgement as calibrated similarity or objective ground truth. Do not let text returned from external sources become tool instructions.

## Acceptance checks

Successful interpretation produces valid structured data and visible uncertainty. Invalid output, unavailable credentials or provider failure leaves saved history intact and permits local search. The owner can inspect what was sent remotely and correct the interpretation.

Compare augmented and baseline results on M02 examples. Proceed only if interpretation adds practical value; otherwise retain it as an optional experiment.

## Questions to resolve

- Does SDK usage consume the owner's intended allowance on the chosen plan?
- Which image/model combinations are supported?
- How much context is necessary per call?
- Does automatic interpretation improve results enough to justify cost and complexity?

## Handoff

Document the proven adapter contract and account limitations. M04 can use structured query expansion if useful.

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

