# The author cell-type column benchmark

The `author-celltype-columns` skill claims mean Jaccard 0.81 against hand
curation. This is where that number comes from, what it does and does not cover,
and what has changed since it was measured.

## What was measured

73 CELLxGENE datasets, drawn from CL_KG curation sheets across the HCA, Gut
Atlas, lung, skin and brain collections. For each, curators had recorded by hand
which `obs` columns hold author cell-type annotations. An agent was shown a
schema-and-samples summary of every obs column and asked to pick the cell-type
ones; the picks were scored against the curation.

| metric | n=73 |
|---|---|
| mean Jaccard | 0.811 |
| mean precision | 0.823 |
| mean recall | 0.969 |
| hit rate (≥1 correct column) | 72 / 73 |

Recall is the easy part. Precision is what the picker rules are mostly about.

A random-pick null model over the actual obs schema sizes is computed alongside,
because "picked at least one right column" is not impressive on its own when a
dataset has four cell-type columns out of forty.

The gold set, the metrics and the frozen picks all ship in
[`packages/celltype-column-eval`](../packages/celltype-column-eval), so the
number is reproducible rather than quoted:

```sh
celltype-column-eval score \
  packages/celltype-column-eval/src/celltype_column_eval/data/frozen/n73_picks.json
```

## Provenance, and one correction

The run was done in
[agent_celltype_eval](https://github.com/Cellular-Semantics/agent_celltype_eval)
and reproduced in `cxg-author-probe`, whose rewritten pipeline scored 0.814
(95% CI 0.74–0.88) on the 42 datasets that completed before a spend cap stopped
the run — statistically indistinguishable from the original 0.819 on the same
42.

The curation snapshot shipped here includes a typo correction made after the
original scoring. Rescoring the untouched frozen picks against it gives 0.8114
rather than the published 0.8079. The picks are the original artefact and have
not been edited; both figures are recorded in `data/frozen/n73_scores.json`.

## What has changed, and why the number needs re-earning

The pipeline that produced 0.81 is not the pipeline in this repo. Three
differences matter:

1. **Sample values are spread across the table, not taken from the head.** obs
   is routinely sorted by donor or cluster, so a head sample of a sorted column
   shows one value. The old profile could not distinguish that from a genuinely
   constant column, and the picker had to guess. This should help.
2. **The profile reports `(constant)` explicitly**, and reports whether a
   cardinality is exact or estimated. Rule 4 previously had to be inferred from
   `n_unique == 1`.
3. **The picking rules live in exactly one place.** In the old pipeline the
   rendered prompt carried rules 1–2 and the sub-agent definition carried rules
   1–7; the three rules added latest — reject numeric-only columns, reject
   constant columns, include varying lineage columns — went into the agent only
   and never reached the prompt. The profile here is data with no instructions
   in it, so that class of drift cannot recur.

Changes 1 and 2 give the picker information it did not have, and change 3 means
the rules it is given are the rules that were written. All three point the same
way, but **none of them has been measured on the full set here**. Treat 0.81 as
the figure for the predecessor and the thing to beat, not as a claim about this
skill.

### First indication, on six datasets

Run 2026-09-28, before the plugin was published, so the *rules text* was fed to
a bare `claude -p --model sonnet` rather than dispatched as the packaged
sub-agent. Six datasets, $0.52.

| | this rules text | frozen n=73 picker, same six |
|---|---|---|
| mean Jaccard | 0.833 | 0.583 |
| hit rate | 5/6 | 5/6 |

Five of six exact. The three traps the subset was chosen for all held: `leiden`
and `louvain` rejected where the frozen picker took them, `seurat_clusters`
rejected without losing `author_cell_type` beside it, and a constant `Lineage`
rejected while the varying `Cell.class`/`Cell.group` were kept.

Two caveats, both load-bearing:

- **n=6 and the subset is not random** — it was chosen to contain the traps. It
  is a regression check, not an estimate. The full-set number is the one that
  can be compared to 0.81.
- **One rule was added because of this run.** `cre`, holding mouse driver lines
  (`Calb2`, `Rorb`, `Gad2`), was picked on the Patch-seq dataset; the values are
  marker gene symbols and track cell class closely, which is what makes it
  tempting, but it says which animal the cell came from. Rule 2 now rejects
  driver lines and reporter genotypes explicitly. That took the subset from
  0.778 to 0.833 — a rule fitted on one observation and **not yet measured
  anywhere else**.

The one remaining miss is a disagreement, not clearly an error: on the
all-constant dataset the picker rejected every constant column, as intended, and
then offered `sub_cluster` (`plt_0`…`plt_4`), which does vary per cell. The
curation records nothing for that dataset, so it scores zero. Rule 3 explicitly
permits mixed letter-and-digit names, and the pick is defensible.

## Running it

The eval harness is in [`evals/`](../evals). Six datasets by default:

```sh
python3 evals/runner.py --tag picker
```

The full 73 is `--all-datasets`, and is slow and not free. See
[`evals/README.md`](../evals/README.md).

## Limits

- **CELLxGENE only.** The skill is portal-agnostic; this gold set is not. It is
  a good cross-section — 74 datasets from 1.7k to 4M cells, across brain, gut,
  lung, kidney, skin and immune atlases, with every common author naming
  convention in it — but nothing here tests an atlas from another portal.
- **The curation is a snapshot and is itself hand work.** Some disagreements in
  the n=73 run were the curation being wrong, not the agent. Reported precision
  is therefore a lower bound.
- **Three of the 74 datasets have no curated cell-type column.** For those the
  correct answer is to pick nothing, which is a real and useful case, but it
  means "curated columns" and "columns that exist" are not the same set.
- **One dataset's obs could not be read** at snapshot time. It is kept in the
  manifest rather than dropped, so coverage is not quietly overstated.
