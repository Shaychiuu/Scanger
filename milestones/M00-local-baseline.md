# M00 — Reproduce the local baseline

Status: not started  
Last edited: 2026-10-23  
Prerequisites: None. Start here.  
Owner review: pending

[Overview](../../PROJECT_OVERVIEW.md) · [Milestone index](../../README.md)

This is an editable build plan. Implement one agreed slice at a time; stop at the milestone boundary for owner review. No task below has been completed by creating this document.

## Outcome

Run the unmodified or minimally repaired baseline on the owner's machine and demonstrate an image search and an image-plus-text search. Establish what works before introducing persistence or changing retrieval.

## Scope

Use the upstream frontend and retrieval implementation. This phase has no app database changes, hosted model calls, retailer searches or custom scoring.

## Build slices

### 0.1 Inspect and record prerequisites

- [ ] Inspect the upstream checkout and record its commit and license status.
- [ ] Identify dataset source, access procedure, use terms and available metadata.
- [ ] Identify required model weights, index artifacts and build scripts.
- [ ] Record OS, Python options, CPU, available RAM, GPU/VRAM if any and free disk space.
- [ ] Estimate download/index size from actual artifacts before starting large work.
- [ ] Decide whether to reproduce a small subset first; label any subset explicitly.

If licensing or dataset access prevents adoption, record the blocker and discuss an alternative with the owner. Do not silently substitute an unrelated dataset and call the original baseline reproduced.

### 0.2 Establish the environment

- [ ] Create an isolated Python environment.
- [ ] Install the inspected dependencies and record necessary platform-specific adjustments.
- [ ] Keep changes minimal and preserve the original dependency inventory.
- [ ] Configure dataset/model/index paths without hardcoding the owner's home directory.
- [ ] Keep artifacts outside Git and record their source and revision.
- [ ] Build or load a compatible index; check count, dimensions and ID-to-image mapping.

### 0.3 Run and inspect

- [ ] Discover actual frontend/backend launch commands from the checkout.
- [ ] Bind services to localhost; do not enable a public sharing tunnel.
- [ ] Run one text, one image and one composed query.
- [ ] Verify that returned IDs resolve to the displayed images.
- [ ] Record cold-start time, representative warm-query latency and peak memory if practical.
- [ ] Restart and reproduce the same basic workflow.

## Acceptance evidence

The owner can select an image and enter text, obtain a non-empty result grid and identify the active model/index and dataset. The documented commands work from a fresh shell. Explain any subset, missing artifact, workaround or unsupported device.

Do not interpret successful retrieval as proof of useful matching quality; that is M02.

## Questions to resolve

- Is the dataset accessible under acceptable terms?
- Are usable prebuilt indexes available, or must they be built locally?
- Which upstream model/configuration is the simplest working baseline?
- Does the UI support the needed inputs as implemented?
- What minimum dependency changes were necessary?

## Handoff

Record working commands and configuration below. M01 may begin when the owner accepts the baseline.

| Item | Observed value |
| --- | --- |
| Checkout commit | Pending |
| Environment | Pending |
| Dataset manifest | Pending |
| Model/index | Pending |
| Backend launch command | Pending |
| Frontend launch command | Pending |
| Timing/memory | Pending |

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

