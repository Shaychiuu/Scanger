# Clothing Search — project documentation

Created: 2026-10-24

This is a documentation starter for a local, personally supervised clothing-search project. The overview is stable context; milestone files are editable build plans.

## Start here

1. Read [PROJECT_OVERVIEW.md](PROJECT_OVERVIEW.md).
2. Begin with [M00 — reproduce the local baseline](docs/milestones/M00-local-baseline.md).
3. Implement one small task at a time, review the result, and update that milestone.
4. Move to the next milestone only when the project owner chooses to do so.

The immediate goal is a local image-and-text search experience over a fixed fashion dataset, with persistent sessions. Web search, crawling, hosted LLM interpretation and retailer assessment are later work.

## Plans

| Order | Plan | Outcome |
| --- | --- | --- |
| M00 | [Local baseline](docs/milestones/M00-local-baseline.md) | Upstream retrieval and frontend work on the owner's machine |
| M01 | [Persistent sessions](docs/milestones/M01-persistent-sessions.md) | Upload, prompt, search, restart and reopen a session |
| M02 | [Retrieval quality](docs/milestones/M02-retrieval-quality.md) | Measure whether returned images match the owner's intent |
| M03 | [Cursor SDK interpretation](docs/milestones/M03-cursor-sdk.md) | Optional structured interpretation and comparison |
| M04 | [Web discovery](docs/milestones/M04-web-discovery.md) | Find candidate URLs beyond the local dataset |
| M05 | [Product extraction](docs/milestones/M05-product-extraction.md) | Turn live product pages into comparable candidates |
| M06 | [Merchant and delivery evidence](docs/milestones/M06-evidence.md) | Assess review and shipping evidence without hiding uncertainty |
| M07 | [Recommendations and reports](docs/milestones/M07-recommendations.md) | Explain a shortlist, tradeoffs and remaining unknowns |

All milestones start **not started**. M00 is the recommended first task, not a claim that implementation is underway.


## Editing conventions

- Check a task only after it is verified.
- Record actual commands, versions, errors and measurements where the plan asks for them.
- Label assumptions and decisions separately from observed behaviour.
- Preserve failure cases and reasons for changing direction.
- Revise future milestones when learning changes the design.
- Read [SOURCES.md](docs/SOURCES.md) for provenance and verification limits.


