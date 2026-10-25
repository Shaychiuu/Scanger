# M02 — Evaluate and improve local matching

Status: skipped  
Last edited: 2026-10-23  
Prerequisites: M01 accepted; local history is usable.  

[Overview](../../PROJECT_OVERVIEW.md) · [Milestone index](../../README.md)

## Skipped

This set up was AI-generated. It was kept for the rigerous sentiment, but it is too formal.
Setting up such a controlled experimentdnvironment is a good for conducting research.
But the required time investment is an overkill since this is a hobby project.
So the method for this will be trial & error - styled instead. Manual testing.

Update: Retrieval quality is sufficient as we are now wrapping a finetuned Fashion Clip. 


---------------------------------------------------------------------------

## Outcome

Know whether the local results are close enough for the owner's use, identify failure patterns and decide whether to extend to the web or improve retrieval first.

## Scope

Small personal evaluation set, saved feedback and targeted retrieval improvements. Keep the existing offline path usable. Do not train a new model or add several model families by default.

## Build slices

### 2.1 Establish an evaluation set

- [ ] Select approximately 15–20 representative reference queries, adjustable to the owner's time.
- [ ] Include image-only, text-only and composed queries.
- [ ] Include external photographs and difficult edits such as collar, length and exclusion changes.
- [ ] Keep catalogue self-match checks separate from realistic reference-photo tests.
- [ ] Write intended attributes and unacceptable mismatches before judging results.
- [ ] Fix the dataset/index and record the baseline configuration.

### 2.2 Add simple human feedback

- [ ] Allow useful / partial / poor judgements and a short reason.
- [ ] Attach feedback to the specific run/result, not just the session.
- [ ] Export evaluation records without copying the dataset.
- [ ] Record missing-catalogue cases separately from retrieval failures.

Suggested metrics: fraction of queries with at least one useful result in the top five; proportion of judged top-five results considered useful; explicitly requested attribute satisfaction; warm-query latency. Call these personal evaluation metrics. Use formal recall only if a sufficiently complete relevance set exists.

### 2.3 Run controlled experiments

- [ ] Compare image-only and composed retrieval on the same references.
- [ ] Inspect preprocessing, crop/background sensitivity and image-text weighting.
- [ ] Change one variable per experiment and save configuration with results.
- [ ] Consider a different embedding model only when failure evidence justifies it.
- [ ] Rebuild compatible index embeddings for any model/preprocessing change.
- [ ] Retain the accepted baseline for comparison and rollback.

An optional FashionCLIP experiment can be planned here after inspecting its current compatibility and terms. It is not mandatory. Do not add an LLM just to disguise a poor baseline.

## Acceptance checks

The owner reviews the fixed evaluation set and records an explicit proceed/improve decision. Establish a target before tuning; an initial discussion target could be “at least one useful top-five result on 70% of representable queries.” This is a proposed threshold, not a demonstrated result or universal standard.

No regression should silently change saved history. Score values are labelled as model/index-specific. A change that improves an aggregate but breaks the owner's important garment category is documented.

## Questions to resolve

- Which attributes matter most to the owner?
- Are failures caused by catalogue coverage, image domain, text composition or ranking?
- Does the proposed threshold reflect practical usefulness?
- Would crop support solve more problems than a model change?

## Handoff

Record accepted configuration and remaining failure cases. The owner may revise M03 or proceed only after accepting the limitation profile.

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

