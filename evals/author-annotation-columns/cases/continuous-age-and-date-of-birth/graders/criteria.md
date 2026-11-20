# continuous-age-and-date-of-birth

A Patch-seq mouse primary-motor-cortex dataset. 94,243 cells x 53 obs columns.

## The curated answer

- `development_stage`: **`Mouse age`**.
- `tissue`: **`Targeted layer`** and **`Inferred layer`**, or an explicit statement
  that the atlas is single-tissue and records only cortical layer.

## Why this case exists

Three traps, all in one dataset.

**`Mouse age` profiles as `continuous 36..105 (90% numeric)`.** It is a float column
with roughly one distinct value per scanned row, because Patch-seq records one animal
per cell. An agent that treats `continuous` as disqualifying — which is the correct rule
for tissue, disease and other_stage — throws away the only age column in the dataset.
This is the one field type where the column *name* has to outrank the measurement cell.

**`Mouse date of birth` sits right beside it**, with 81 date-valued categories. An age is
derivable from it. That is not the same as being one, and picking it is the failure.

**`Targeted layer` and `Inferred layer` profile as `bounded 1..6 (60% numeric)`.** They
are cortical layers, which are anatomical structures with UBERON terms, so they are
tissue — despite reading exactly like small integer codes. Accepting them is good;
missing them is a forgivable miss, and the deterministic checks do not require them.
Calling them a cluster index in the reasoning is a clear error.

`tissue` and `disease` are CELLxGENE's, both `(constant)`, and never picks.

Measured 2026-09-29 with h5ad-obs 0.3.0.
