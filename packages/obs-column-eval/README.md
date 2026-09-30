# obs-column-eval

The gold sets and the metrics for scoring *which obs columns hold which kind of
author annotation*. Five field types: `cell_type`, `tissue`,
`development_stage`, `other_stage` and `disease`. It does not pick anything —
give it picks from any source and it tells you how they compare to hand
curation.

The evidence behind the five is very uneven, and the package is built so that
shows rather than hides: `cell_type` has 165 curated datasets, the other four
have one. See [`docs/sample-fields.md`](../../docs/sample-fields.md).

## What ships here

- **The curation snapshot** (`data/curation/`) — ten CL_KG sheets covering 165
  CELLxGENE datasets, frozen. **`cell_type` only.** The sheets record one
  distinction, cell-type field or not, so tissue, age, batch and QC all share a
  single undifferentiated `other` bucket. That makes them a source of
  candidates and of negatives, never of tissue, stage or disease ground truth.
- **The hand-curated entries** (`data/sample_fields/`) — one JSON file per
  dataset, naming the columns for each field type it was curated for, plus
  `notes` arguing the calls that were not obvious. Currently one entry.
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
obs-column-eval datasets                      # the six default datasets + ground truth
obs-column-eval datasets --all                # all 74
obs-column-eval gold                          # ground truth, keyed by field type
obs-column-eval gold --field-type tissue      # one field type
obs-column-eval notes                         # why the awkward calls went that way
obs-column-eval curation                      # the raw CL_KG sheets
obs-column-eval score picks.json --baseline
obs-column-eval candidates <profiles-dir>     # what to hand-curate next
```

`picks.json` takes three shapes. `{dataset_id: [column, ...]}` and
`{dataset_id: {"picks": [...], "reasoning": "..."}}` are cell-type picks — the
shape of every file written before field types existed, including the frozen
baseline, and they keep scoring unchanged. `{dataset_id: {"tissue": [...],
"disease": [...]}}` is what the sample-field agent writes.

`score` reports per field type. **A dataset is only scored on a field type it
was curated for**; otherwise every correct tissue pick on a cell-type-only
dataset would count as a false positive, and the number would describe the gold
set's coverage rather than the agent.

`candidates` mines a directory of text obs profiles by column name to narrow
what a curator reads next. It is an aid and says so in its own output — a name
match is not evidence. `--miss` lists what no pattern caught, which is where a
field type nobody thought to name is hiding.

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
