# M03 — Optional Cursor SDK interpretation

Status: Finished 
Last edited: 2026-10-23  
Prerequisites: M02 reviewed; local retrieval remains available independently.  

[Overview](../../PROJECT_OVERVIEW.md) · [Milestone index](../../README.md)

This is an editable build plan. Implement one agreed slice at a time; stop at the milestone boundary for owner review. No task below has been completed by creating this document.

## Outcome

Use Cursor's Python SDK for a bounded, optional image-and-text interpretation step. Later use the same adapter for shortlisted image comparisons. Validate the integration before depending on it for discovery.

## Scope

One provider adapter, explicit image transmission, structured outputs and usage recording. No web search tools, shell-driven shopping agent or unrestricted autonomous loop.

## Build slices

### 3.1 Verify the SDK independently

- [x] Establish an isolated workspace and narrow available tools/permissions.
- [x] Record how secrets are configured and how remote processing is disclosed.

Use https://cursor.com/docs/sdk/python as the integration reference. Do not assume the current documentation examples or billing arrangements remain unchanged.

### 3.2 Define an app-owned interpretation contract

- [x] Preserve raw user text and the original reference.
- [x] Add garment category, observed visual attributes, requested changes, must-have attributes, exclusions and uncertainties.
- [x] Distinguish user assertions, visually inferred properties and unknown material composition.
- [x] Validate responses with a typed schema and a schema/prompt version.
- [x] Show interpreted attributes for owner correction before using them as constraints.
- [x] Save provider/model metadata, latency, usage when available and failure state.

The SDK response envelope being JSON does not guarantee that its generated content matches the application's schema. Parse and validate explicitly.

### 3.3 Connect interpretation to the local workflow

- [x] Put SDK calls behind an optional adapter.
- [ ] Keep image-only/text-only baseline searches working without credentials.
- [x] Use corrected attributes to construct a query while retaining the original request.
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
| 2026-10-25 | 3.1 probe: `cursor-sdk==1.0.40`, `scanger/interpret.py` (text-only agent, empty temp cwd, compact JSON prompt `interpret-v0`) | Offline tests pass; no SDK call made yet | Owner adds key, lists models, picks Claude Haiku 5.5 with thinking off, sends one test image |
| 2026-10-25 | Owner ran `interpret-v0` on a brown belted puffer image with "fluffy hood instead of the fur collar" | Valid JSON; query better than "brown jacket". Most fields unused in the single query; `category` still names the excluded fur collar; query added unstated "faux fur" | Try `interpret-v1` |
| 2026-10-25 | `interpret-v1`: `search_query` replaced by `queries` {precise, synonym, broad}; queries limited to visible or stated details | Offline tests pass; not yet run on the account | Owner reruns the same image and text, compares with v0 |

## Decisions and plan changes

| Date | Decision | Reason / alternatives | Consequence |
| --- | --- | --- | --- |
| Pending | — | — | — |


