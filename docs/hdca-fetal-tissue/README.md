# HDCA fetal tissue — mapping corpus

Real tissue descriptions from human fetal single-cell datasets, the mappings
the `map-to-ontology` skill produced for them, and a curator's scoring of
those mappings. Kept together because the next piece of work on this skill —
evals, tuning, or a regression set — starts from these files rather than from
new data.

Nothing here is a gold set yet. `results-opus-scored.xls` is one reviewer's
pass over 49 records and is the closest thing to one; see *What is signed off*
below for what that does and does not establish.

## Files

| file | what it is |
|---|---|
| `source-review-table.tsv` | As supplied. 865 library rows, one per library. |
| `review-sheet.tsv` | The 181 distinct tissue descriptions, with the four source columns verbatim and blank columns for expected terms. |
| `results-opus.tsv` | 49 records mapped, Opus, one record per agent process. |
| `results-opus-scored.xls` | `results-opus.tsv` with a curator's `agree` and `reviewer_note`. |
| `results-opus-vs-sonnet.tsv` | 70 records: 49 paired Opus/Sonnet, 21 Sonnet-only. |

## The unit is a description, not a library row

865 library rows collapse to **181 distinct tissue descriptions**. Library and
donor do not change the mapping, so the description is the unit of work and of
scoring. `review-sheet.tsv` is keyed on the four source columns verbatim, so
two rows group together only when the source really is identical.

`tissue_obs` and `tissue_dataset_metadata` are **separate provenance** and are
kept apart everywhere here. An earlier version of the sheet merged them; no
key appeared in both and no value differed where one could have, so nothing
was lost, but the merge was wrong in principle and should not be reintroduced.

## Context lives outside the tissue fields

`publication_id` is load-bearing, not decoration. `region=apex` is unmappable
alone — apex of heart, lung or tongue — and `bayraktar_2024_heart` is what
makes it the heart. Any harness built on these files must pass the publication
to the skill, not merely group by it.

`tissue_study_level` is a fallback: it is populated only where both per-library
columns are empty (107 rows, 9 publications, zero overlap). For seven
publications it is one constant; for `sridhar_2020_retina` it carries a
per-library distinction (`retina; central` vs `retina; peripheral`), so the
column name slightly oversells how study-level it is. How it was derived
upstream is not recorded here, which matters for provenance: a value that came
from a figure or a methods section has different standing from a submitter's
own field, and nothing distinguishes them.

## What is signed off, and what is not

Of 49 scored records: **42 agree, 1 disagree (U153), 1 marked `?`, 5 blank.**
Twenty carry a note. No `corrected_curie` was filled, so where the reviewer
disagreed the right answer is not yet recorded.

Several notes are about the *method* rather than the term, and those are the
ones worth mining before the next tuning round:

- *"Excessive effort for simple mapping?"* (U030) and *"Lots of thought went
  into making a simple mapping"* (U129) — proportion, which the skill claims
  to care about and evidently does not always achieve.
- *"Reasonable mapping given text, but perhaps we should flag these are not
  cleanly [mapped]"* — four `haniffa_2026_fetus` records whose values
  reference a diagram absent from the record. The skill answered; arguably it
  should have flagged.
- *"But I have given no instructions on how to deal with clashes"* (U153) —
  the one disagreement, and the reviewer attributes it to missing guidance
  rather than to the skill misapplying what it has.
- *"'Central' might be an upstream hallucination (on input)"* (U134) — a
  reminder that the source table is itself derived and not above suspicion.

## Coverage is uneven, and not a sample

`results-opus.tsv` is 49 of 181 because the run was stopped part way. The
paired Opus/Sonnet set over-weights `braun`, `bayraktar`, `haniffa` and
`lorenzi`, and contains no `thyroid`, `pancreas` or `lung` at all — eight
publications appear only in the Sonnet column.

So **do not quote an agreement rate from these files as though it generalised
to the corpus.** The selection was purposive for the first 20 (chosen to
exercise each move) and truncated for the rest. For a measurement rather than
a worked set, the sampling has to be redone.

## Reproducing or extending

```
python3 evals/ontology-mapping/run-batch.py \
    --slice evals/ontology-mapping/slice-20.txt \
    --batch-size 5 --model sonnet --out <results>.json
```

Reads `review-sheet.tsv` from this directory. Each record runs against the
**installed** plugin in a fresh temporary directory, so check `claude plugin
list` before trusting a run — a plugin installed from a marketplace copy does
not change when the working tree does.

Run it under `caffeinate -dimsu`. Every long run here was interrupted at least
once by the laptop sleeping, which surfaces as
`API Error: Your computer went to sleep mid-response` and looks exactly like a
stall.

This runner is **not** a scorer, and these records have no expected answers.
`evals/ontology-mapping/check.py` is the scorer and needs a gold set — which
is what filling in `corrected_curie` here would start to build.
