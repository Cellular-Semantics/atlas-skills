# exposure-is-not-disease

A COVID-19 PBMC atlas. 422,220 cells x 34 obs columns.

## The curated answer

- `disease`: **`COVID_status`** (`Healthy`, `COVID-19`, `Post-COVID-19`).
  **`COVID_severity`** (`Healthy`, `Severe`, `Asymptomatic`) is a defensible second pick
  — its values mix a severity scale with a health state — and is neither required nor
  penalised.
- `development_stage`: **`Age_group`** (`Adult`, `Infant`, `Neonate`, `Child`,
  `Elderly`) and **`Group`** (`Adult`, `Paediatric`).
- `tissue`: **nothing**. The only tissue column is CELLxGENE's, `(constant)` at
  `'blood'`. An empty tissue list, stated as a finding, is the right answer.

## Why this case exists

`Smoker` (`Non-smoker`, `Ex-smoker`, `Smoker`) and `BMI` (`bounded 6.8..37.11`) are
facts about the donor's body and behaviour that sit in the same block of columns as the
disease fields and correlate with outcome. They are not diagnoses. `Ethnicity` is
demographics and belongs to no field type here.

`BMI` also tests the numeric rule from the other side: it is bounded, it is numeric, and
its range is plausible for a measurement — everything except a reason to pick it.

The empty tissue answer matters as much as the picks. A single-tissue atlas states its
tissue in the metadata, and reaching for `sample_id` or `sequencing_library` to fill the
gap is the failure mode this case watches for.

Measured 2026-09-29 with h5ad-obs 0.3.0.
