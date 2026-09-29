# celltype-column-eval

The gold set and the metrics for scoring *which obs columns hold author
cell-type annotations*. It does not pick anything: give it
`{dataset_id: [column, ...]}` from any source and it tells you how that compares
to hand curation.

## What ships here

- **The curation snapshot** (`data/curation/`) — ten CL_KG sheets covering 165
  CELLxGENE datasets, frozen. Only rows whose `Content` names a cell-type field
  count as ground truth; the sheets also record clonotypes, donor ids and
  demographics.
- **The test set** (`data/manifest.json`) — the 74 CELLxGENE datasets the n=73
  benchmark ran on, with their CDN URLs and obs shapes. One is unreadable and is
  kept as such rather than dropped.
- **The default subset** (`data/subset.json`) — six datasets, each with a written
  reason for being there. Running all 74 is slow and not free; this is what the
  eval runs by default.
- **The frozen baseline** (`data/frozen/`) — the n=73 picks and scores behind the
  published Jaccard 0.81, so a new run can be compared like for like.

## Use

```sh
celltype-column-eval datasets            # the six default datasets + ground truth
celltype-column-eval datasets --all      # all 74
celltype-column-eval curation            # the gold set, per dataset
celltype-column-eval score picks.json --baseline
```

`picks.json` is `{dataset_id: [column, ...]}`, or `{dataset_id: {"picks": [...],
"reasoning": "..."}}` — an agent writing its reasoning alongside does not have to
strip it first.

`score` reports mean Jaccard, precision and recall with bootstrap CIs, a Wilson
interval on the hit rate, and per-dataset rows naming what was missed and what
was picked spuriously.

## Provenance

The curation is hand work by the CL_KG curators across the HCA, Gut Atlas, lung,
skin and brain collections. The n=73 benchmark was run in the
[agent_celltype_eval](https://github.com/Cellular-Semantics/agent_celltype_eval)
and `cxg-author-probe` repos; this package carries the gold set and the metrics
forward unchanged so the numbers stay comparable.

**The frozen numbers describe the pipeline that produced them**, not the skill in
this repo. See `docs/benchmark.md` for what changed and what that means for the
headline figures.
