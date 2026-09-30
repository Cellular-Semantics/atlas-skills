# Tissue, developmental stage and disease

How `author-annotation-columns` identifies the obs columns holding the authors'
own tissue, developmental-stage and disease annotation, what evidence exists for
it, and what does not.

Read [`benchmark.md`](benchmark.md) first for the cell-type arm. This page is
about the three field types added alongside it, which are at a much earlier
stage of evidence.

## State of the evidence

**There is no benchmark number, and quoting the cell-type figures for these
field types would be wrong.** What exists:

| | cell type | tissue / stage / disease |
|---|---|---|
| gold set | 165 datasets, CL_KG hand curation | **1 dataset**, hand-curated here |
| test set scored | 73 CELLxGENE datasets | none |
| headline metric | Jaccard 0.94 | — |
| candidate pool | — | 96 column names across 73 datasets |

The picker agent was written against real data — the reproductive-atlas gold
entry, and the 73 committed obs profiles — but it has not been *scored* against
anything. Its picks are a proposal to be checked, and the skill says so in its
output.

## Why the CL_KG sheets are not a gold set for this

The CL_KG curation records one distinction: cell-type field or not. Every other
column lands in an undifferentiated `other` bucket — 1,134 rows across the ten
sheets — and that bucket mixes the field types we now want with batch, QC and
ids:

```
17  Layer            13  batch            8  age
10  _Region          10  _pool            7  timepoint
 6  Region            9  library_uuid     7  disease_general
 6  Subregion         9  sample_uuid      6  Smoker
```

So the sheets are a **source of candidates and of negatives**, never of tissue,
stage or disease ground truth. `obs_column_eval.gold` enforces this: an entry
records which field types it was `curated_for`, and the scorer skips any
dataset/field-type pair nobody looked at. Scoring a tissue pick against a
cell-type-only dataset would count every correct answer as a false positive and
measure the gold set's coverage rather than the agent.

## The gold set that does exist

One entry, `HCA_reproductive_atlas_v1` — the integrated HCA reproductive atlas,
2,235,448 cells and 54 obs columns. It was chosen because it is unusually dense
in hard cases rather than because it is representative:

| field type | columns |
|---|---|
| `cell_type` | 17, across the HCA master nomenclature and nine contributing studies |
| `tissue` | `Organ`, `Organ_part`, `Tissue_ROI` |
| `development_stage` | `Developmental_stage`, `Gestational_age_pcw`, `Postnatal_age_years`, `Tanner Stage` |
| `other_stage` | `Menstrual_stage`, `Menstrual_stage_OriginalAuthors`, `phase` |
| `disease` | `Clinical_diagnosis`, `Disease`, `Observed_pathology`, `Sampled_site_condition`, `Tissue_status` |

It was seeded from the atlas curators' own `composition.category` labels in
`cas.json` and then extended by hand to every column. `obs-column-eval notes`
prints the reasoning on each awkward call; two of them depart from the original
curation and are argued there:

- **`Menstrual_stage`** was `unclassified` in `cas.json` and is `other_stage`
  here — a real, mappable, cyclical phase that is not a point in development.
- **`Tanner Stage`** was `development_stage` there and stays here, with the
  caveat recorded that `Pubic V/Genitals-Breast V` needs a lookup table before
  it is an ontology term.

## Where `other_stage` came from

Splitting `development_stage` from `other_stage` costs nothing at pick time and
saves a downstream value mapper from being handed terms it cannot map. Menstrual
phase, oestrous phase and cell-cycle phase are all real and worth picking, and
none of them resolves to HsapDv or MmusDv. `phase` (`G1`/`S`/`G2M`) is the only
per-cell entry in any stage bucket, which is the sharpest argument for keeping
the split.

## The measurement filter, and what it costs

`h5ad-obs` 0.3.0 added a measurement cell to the profile: whether a column's
values are numbers, whether its distinct count grows with the cell count
(`continuous`) or not (`bounded`), and the range. Without it, an age and a QC
score are both just numbers.

Measured over the 73 committed profiles:

| | count |
|---|---|
| numeric columns marked `bounded` | 147 |
| ...of which none of the four field types | 133 |
| numeric columns marked `continuous` | 315 |
| ...of which real ages | 3 |

Both error directions are real, and the agent is written for both:

- **Bounded is not sufficient.** `Batch` profiles as `bounded 1..4 (67%
  numeric)` and `seurat_clusters` as `bounded 0..29`. 133 of 147 bounded
  numerics were not picks.
- **Continuous is not disqualifying for age.** `Mouse age` is `continuous
  35..245` in a 636-cell Patch-seq set with one animal per cell, and
  `age_or_mean_of_age_range` is `continuous 0..81` in a 2.3M-cell atlas. Both
  are real ages.

So the filter cuts the numeric pool hard and decides nothing. For age — and only
for age — the column *name* outranks what the values show, which is the reverse
of the cell-type rule and the main reason these are two agents rather than one.

## The candidate pool

`obs-column-eval candidates evals/fixtures/profiles` mines the committed
profiles by column name. Over 73 datasets and 672 distinct column names:

| field type | candidate names |
|---|---|
| `tissue` | 46 |
| `development_stage` | 22 |
| `other_stage` | 2 |
| `disease` | 26 |
| unmatched | 552 |

This is **a curation aid and not ground truth**, and the module says so in its
own output. The patterns are deliberately over-broad: `Lineage` matches the age
pattern because it contains the letters "age" and is a cell-type column. The
`--miss` list matters as much as the hits — it is where a field type nobody
thought to name is hiding.

Several of the agent's named traps were found this way rather than invented:
`Mouse date of birth`, `age_onset` beside `age_death`, `days_since_onset`,
`Hospital day`, `intubation_days`, `Smoker`, `BMI`,
`cv19_vax_boost_or_HC_status`, and the `PreExistingHeartDisease` family.

## What would make this a benchmark

In order, and none of it is done:

1. Hand-curate 30–40 of the 73 datasets from the candidate pool, holding back a
   third. The pool makes this a few hours rather than a few days.
2. Add a prenatal atlas or two — the CELLxGENE test set is adult-heavy, and
   gestational-age fields are exactly where the numeric rule earns its keep.
3. Run the picker over the held-out third and score with
   `obs-column-eval score picks.json --field-type tissue ...`.
4. Freeze the result the way `data/frozen/` freezes the n=73 cell-type picks.

Until then the honest statement is the one the skill makes: these picks are a
proposal, and the answer should name them so a spurious one is visible.
