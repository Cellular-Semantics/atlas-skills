# age-at-event-not-collection

A frontotemporal-dementia occipital-cortex snRNA-seq dataset. 66,719 cells x 42 obs
columns.

## The curated answer

`development_stage`: **`age_death`** alone.

## Why this case exists

Three age-shaped columns sit side by side and only one is the donor's age at collection:

```
age_onset | categorical[10 cats] | 10 | bounded 52..66 (90% numeric) | 'nan', '64.0', '52.0', ...
age_death | categorical[14 cats] | 14 | bounded 58..96              | '83', '73', '96', '58', ...
duration  | categorical[7 cats]  |  7 |                             | 'nan', '9 yrs', '6 yrs', ...
```

Every one of them is bounded, numeric-looking and in a plausible human range, so the
measurement cell cannot separate them and neither can the values. Only the name can.

- `age_death` is the age of the donor whose tissue this is. This is post-mortem brain,
  so age at death *is* age at collection. Pick.
- `age_onset` is the age the dementia started, a property of the illness rather than of
  the donor at sampling. Reject.
- `duration` is how long the illness lasted. Reject.

CELLxGENE's `development_stage` confirms the reading — `'83-year-old stage'`,
`'73-year-old stage'` — matching `age_death`, not `age_onset`. It is the portal's field
and is not a pick, but an answer that cites it as corroboration is doing the right
thing.

There is no author disease column: `disease` is CELLxGENE's. An empty `disease` list is
correct here.

Measured 2026-09-29 with h5ad-obs 0.3.0.
