# The author cell-type column benchmark

How well `author-annotation-columns` identifies the obs columns holding author cell-type
annotations, measured against hand curation.

**Cell type only.** The same skill also picks tissue, developmental stage and disease,
via a second agent that is *not* measured here and has no comparable number — see
[`sample-fields.md`](sample-fields.md). Do not carry the figures below across to those
field types.

## Latest result

**n=73 CELLxGENE datasets, 2026-09-29**

| | this skill | frozen predecessor, same datasets |
|---|---|---|
| mean Jaccard | **0.940** (95% CI 0.90–0.98) | 0.829 |
| mean precision | 0.958 (0.92–0.99) | 0.843 |
| mean recall | 0.964 (0.92–0.99) | 0.972 |
| hit rate (≥1 correct column) | 72 / 73 | 72 / 73 |

Exact agreement with curation on **63 of 73**. The full per-dataset breakdown — what was
picked, what was curated, what was missed — is in
[`benchmark-results.json`](benchmark-results.json), which also records the plugin
version, commit and a hash of the agent definition that produced the picks.

**Precision is still a lower bound.** The figures above already include the gold-set
corrections accepted in review on 2026-09-29 — four column names that matched nothing in
obs, seven pre-harmonisation HLCA annotations, and an author-asserted CL label. That
took Jaccard from 0.926 to 0.940 and precision from 0.944 to 0.958 with the picker
unchanged, and moved the predecessor by exactly the same amount, so the gap between them
is unaffected.

Of the ten datasets still disagreeing, **two are genuine picker errors** — a numeric
cluster index, and an anatomical `structure` column — two are accepted disagreements,
five hang on open questions about composite and model-predicted labels, and one is
unreviewed. See [`curation-review-2026-09-29.md`](curation-review-2026-09-29.md), which
lists all ten and what each is waiting on.

## What is measured

73 CELLxGENE datasets drawn from CL_KG curation sheets across the HCA, Gut Atlas, lung,
kidney, skin, immune and brain collections — 1.7k to 4M cells, and every common author
naming convention in the wild. For each, curators recorded by hand which obs columns
hold author cell-type annotations; only rows whose `Content` names a cell-type field
count as ground truth, since the sheets also record clonotypes, donor demographics and
sample identifiers.

The picker sees only an obs column profile — name, kind, cardinality, sample values —
in a fresh context per dataset, and returns a list of column names. Those are scored
against the curated set: Jaccard, precision, recall, and hit rate, with bootstrap and
Wilson intervals. A random-pick null over the actual obs schema sizes is computed
alongside, because "found at least one" is unimpressive when a dataset has four
cell-type columns out of forty.

The gold set, the metrics and the frozen baseline all ship in
[`packages/obs-column-eval`](../packages/obs-column-eval), so the numbers are
reproducible rather than quoted.

## Reproducing it

The obs profiles are **committed** under `evals/fixtures/profiles/` — 571 KB for the
whole test set. Re-scoring therefore needs no network and no re-reading of ~1.5 GB, and
the scored inputs cannot shift under a CELLxGENE re-ingest.

```sh
python3 evals/benchmark.py --all --record docs/benchmark-results.json
```

Picks are cached too, so this re-scores instantly until you clear
`evals/.cache/picks/`. A fresh set of picks costs roughly $20 and an hour. See
[`evals/README.md`](../evals/README.md), including how to run it before a release is
tagged.

If the profile format changes, the fixtures must be regenerated and the benchmark
re-scored — `benchmark.py` warns when the installed `h5ad-obs` no longer matches the
version recorded in `fixtures/profiles/PROVENANCE.json`.

## The picks.json check

The hook that guards `picks.json` was measured separately from the picker. It
checks names, not meaning: is each picked column really in obs, is it spelt and
cased as obs has it, and is it not a portal field. The method:

- **Inputs.** The 73 frozen picker answers, each checked against its own
  dataset's profile.
- **Errors.** Synthetic. Each class below is one way a report goes wrong,
  applied to every clean answer it fits. So the rates describe the check
  against these mutations. They do not say how often a real picker makes each
  mistake.
- **`wrong_but_real`.** This class is there to show the limit. It adds a real
  column that the picker should not have taken. The check is not meant to catch
  that; judging it is what the benchmark above measures.

Unmutated: 72/73 frozen answers pass; 0 false rejects; 1 known picker error caught.

| mutation | applied | caught | rate | meant to catch |
|---|---|---|---|---|
| `invented` | 72 | 72 | 100% | yes |
| `recased` | 69 | 69 | 100% | yes |
| `separator` | 51 | 51 | 100% | yes |
| `borrowed` | 72 | 72 | 100% | yes |
| `portal` | 72 | 72 | 100% | yes |
| `portal_term_id` | 72 | 72 | 100% | yes |
| `wrong_field_key` | 72 | 72 | 100% | yes |
| `dropped_field_type` | 72 | 72 | 100% | yes |
| `missing_reasoning` | 72 | 72 | 100% | yes |
| `wrong_but_real` | 72 | 0 | 0% | no |
Reproduce with `python3 evals/picks_catch_rate.py`. `evals/test_picks_catch_rate.py`
pins these numbers in CI. The one known picker error is a frozen answer that
picked `BICCN_ontology_term_id`, which the skill's rules forbid. The check
rejects it unmutated.

## Limits

- **CELLxGENE only.** The skill is portal-agnostic; this gold set is not. It is a good
  cross-section, but nothing here tests another portal.
- **The curation is hand work, and is the thing being compared against.** Section 2 of
  the curation review lists columns it appears to be missing; until those are settled,
  reported precision understates the picker.
- **One dataset cannot be read.** `b1b7e4e0` returns HTTP 403 from the CDN — withdrawn
  or access-restricted, not malformed. It stays in the manifest rather than being
  dropped, so coverage is not quietly overstated.
- **Three of the 74 have no curated cell-type column.** For those the correct answer is
  to pick nothing, which is a real case, but it means "curated columns" and "columns
  that exist" are not the same set.
- **One picker rule was fitted on a single observation.** Rejecting transgenic driver
  lines (`cre`, with values `Calb2`, `Rorb`, `Gad2`) came from one Patch-seq dataset
  during development. It is right on the merits — a driver line says which animal the
  cell came from — but it fires on one dataset in 73, so the full set does not really
  test it.

## History

The predecessor pipeline scored Jaccard 0.81 on the same 73 datasets, in
[agent_celltype_eval](https://github.com/Cellular-Semantics/agent_celltype_eval) and
then [cxg-author-probe](https://github.com/Cellular-Semantics/cxg-author-probe). Its
picks are frozen in the eval package and re-scored on every run as the comparison arm,
which is where the 0.815 above comes from — the small drift from the published 0.8079
is two corrections to the curation snapshot, both recorded in
`data/frozen/n73_scores.json`.

The +0.111 comes from giving the picker better inputs and one set of rules instead of
two: sample values spread across the table rather than taken from the head, an explicit
constant-column flag, and picking rules that live only in the agent definition rather
than being half-duplicated into a rendered prompt.
