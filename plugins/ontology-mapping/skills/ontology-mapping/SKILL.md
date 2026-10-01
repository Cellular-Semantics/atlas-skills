---
name: ontology-mapping
description: Map the sample-level fields of a human single-cell atlas onto ontology terms — tissue to UBERON, developmental stage to HsapDv, disease to MONDO, sex to PATO, species to NCBITaxon — for CELLxGENE / HCA Tier 1. Handles the hard part, which is that the right tissue term depends on the sample's age, sex and disease state. Produces validated term ids with a stated basis, and a reviewable queue of everything it refused. Use when someone has author strings ("13 pcw", "fetal liver", "GW 15", "reproductive system") and needs ontology ids, or wants existing ids checked.
---

# ontology-mapping

A wrong ontology id is worse than a missing one. It is plausible, it validates,
it propagates into every downstream analysis, and nothing downstream will ever
question it. Everything below is built to **refuse rather than guess**, and to
make every refusal visible and actionable.

## When to invoke

- "map these tissues/stages to ontology terms", "fill in the Tier 1 fields"
- "what UBERON term for …", across a whole sample table rather than one string
- someone has `13 pcw` / `CS13` / `GW 15` in a column and needs HsapDv ids
- checking ontology ids an atlas already carries

**Not** for cell type. `cell_type_ontology_term_id` is a different problem with
different evidence — expression, not strings — and folding it in here would
apply string matching to a question strings cannot answer.

This skill assumes you already know which author column holds which field. If
you do not, run `author-annotation-columns` first.

## What is code and what is judgement

| Layer | Who | Does |
|---|---|---|
| extract, rule ladders, structural inference, dossiers, validation, evaluation | `ontomap` CLI | everything deterministic |
| reading a dossier and deciding | you | assign or decline, with the evidence quoted |

Three rules that hold without exception:

1. **Code never assigns on a similarity score.** Lexical rank is evidence that a
   term exists, never that it is the right one. If no exact or structural rule
   fires, the row gets candidates and **no id**.
2. **You never write an id from memory.** Every id you use must appear in the
   dossier you were given. `ontomap validate` re-checks all of them against the
   live ontology afterwards, and an invented one fails there.
3. **Your output is a separate file**, never an edit to the rule output. The
   `curator` column keeps the two apart permanently, because a considered call
   and a string match carry different warranties.

## The pipeline

Run it in this order. The order is the dependency graph: species decides which
stage ontology applies, and stage, sex and disease are all inputs to tissue.
Getting it wrong does not throw — it quietly produces a mature organ term for an
embryo, which is the kind of wrong that validates.

```sh
# A function, not a variable: zsh does not word-split an unquoted `$VAR`, so
# `ONTOMAP="uvx --from ..."` followed by `$ONTOMAP extract` fails there with
# "no such file or directory" naming the whole command line.
ontomap() {
  uvx --from "git+https://github.com/Cellular-Semantics/atlas-skills@pkg-ontomap--v0.1.0#subdirectory=packages/ontomap" \
      ontomap "$@"
}

# 1. declared columns out of the sample table, units folded in, scope flagged
ontomap extract samples.csv --config config.json --out extracted.json

# 2. the ladders, in dependency order. Tissue runs last and sees the rest.
ontomap map extracted.json --config config.json --out mapped.json

# 3. a dossier per unresolved value, biggest by sample count first
ontomap dossier mapped.json --config config.json --limit 50 --out dossiers.json

# 4. -- you read dossiers.json and write judgements.json (schema below) --

ontomap fold mapped.json --judgements judgements.json --out folded.json
ontomap validate folded.json          # exit 2 on any failed gate: this blocks
ontomap evaluate folded.json --gold gold.json
```

The first `map` run fetches every UBERON label and synonym once (~30 s) and
caches it. Later runs are offline for everything except validation.

## The config

```json
{
  "fields": {
    "species": ["organism"],
    "sex":     ["sex"],
    "stage":   [{"column": "Developmental_stage"},
                {"column": "age", "unit_column": "age_unit", "frame": "post_fertilization"}],
    "disease": ["disease"],
    "tissue":  [{"column": "Organ", "role": "primary"},
                {"column": "Organ_part", "role": "refinement"}]
  },
  "scope_filter": {"column": "in_atlas", "include": ["true"]},
  "boundary": "during"
}
```

Two entries are easy to skip and expensive to skip.

**`scope_filter`.** Archive exports contain samples the project never ingested.
A correctly-mapped `colon` in a thymus study's accession scored as an error
against the gold set because that sample is not in the atlas. Out-of-scope rows
are kept and flagged, never dropped.

**`unit_column`.** Bare numeric ages are unmappable in isolation and the unit
routinely lives in a sibling column. Sixty distinct values were once stranded
for exactly this reason.

Several columns per field is normal and useful. They are resolved independently
and then compared structurally: a refinement that is a **descendant** of the
primary wins, and the descendant edge is the proof it is finer rather than
merely different. Columns that do not subsume each other produce
`column_conflict` and go to a dossier — a disagreement between author columns is
a finding about the source data, not a tie to break.

## Stage is numeric, not lexical

HsapDv carries day-post-fertilization windows on its Carnegie and week terms, so
`CS13`, `13 pcw`, `GW 15` and `92 days` are all parsed to a day and resolved
against the same windows. No conversion table between representations.

What still needs you:

- **Reference frame.** Gestational age counts from the last menstrual period,
  post-fertilization from conception — about two weeks apart, and HsapDv's week
  terms are post-fertilization. A study may write "gestational" and report
  post-conception weeks. Settle it **per study, from the paper**, and put it in
  the config as `frame`; never per string. Every shifted row is flagged.
- **Boundary convention.** Windows abut rather than nest, so day 91 is both the
  end of the 13th week and the start of the 14th. `boundary: "during"` reads
  "N weeks" as *during* the Nth week; `"completed"` reads it as N whole weeks.
- HsapDv also has LMP-based terms, so a gestational value may map directly
  rather than being shifted. Also a per-study call.

## Tissue depends on the other fields

Four context modifiers, applied in this order:

1. **Disease** — a qualifier in the string (`tumour liver`) is stripped to the
   base site and recorded as `sampled_site_condition`.
2. **Composite strings** — split, resolved per part, then rolled up to the most
   specific term *containing* all of them, by `part_of` closure. Containment,
   not classification: liver and thymus are both endocrine glands, and that is
   not a place a sample came from. Parts that span organ systems are refused.
3. **Sex** — a sex-neutral term is specialised only when the anatomy and the sex
   field agree, either able to veto, and only where the ontology asserts the
   specialised term as a descendant. A pooled library is never specialised.
4. **Stage** — the mature term's own EHDAA2 window is asked whether the
   structure existed at the sample's age. Only if it says *no* is a precursor
   looked for, and only a precursor whose window says *yes* is proposed. An open
   window means "cannot say", which is not "no".

Specialisation runs **before** substitution. A precursor usually has no
sex-specific sibling, so the other order drops the sex information every time.

## Writing judgements

`judgements.json` is a list. One entry per dossier you decided.

```json
[{"field": "tissue", "raw_value": "skin",
  "term_id": "UBERON:0002097", "term_name": "skin of body",
  "match_type": "exact",
  "basis": "The organ covering the body that consists of the dermis and epidermis.",
  "rationale": "The only candidate that is the organ rather than a zone of it or its epidermal layer.",
  "curator": "claude"}]
```

`match_type` is one of `exact`, `exact_developmental`, `broad_by_partonomy`,
`broad_by_classification`, `narrow`. For any `broad_` type you must also give
`exemplar_specific_term_id` — a specific structure the string certainly covers —
so `validate` can check the generalisation direction actually holds. Where the
precise structure has no term at all, set `specific_term_missing: true` instead;
the row goes to the new-term request list rather than passing unchecked.

**`basis` and `rationale` are different things.** `basis` is the definition or
axiom text, quoted, so a reviewer can check the evidence without re-deriving
your reasoning. `rationale` is why this candidate and not the others. A
fabricated basis is obvious; a fabricated rationale is not.

**Declining is a valid output.** Omit `term_id`, and record which candidates you
rejected and why none was defensible. Guessing from a one-word string is the
same error as taking a search engine's top hit.

## Reading the output

`row_status` is `complete`, `needs_review` or `out_of_scope`. `needs_review`
will never reach zero; what fraction, weighted by cells, is releasable is a
project decision.

A **rising refusal count after a fix is good**. Coverage falling because false
mappings were withdrawn is progress, and the summary names the count
`refused_or_unresolved` rather than anything that sounds like a shortfall, so
nobody optimises it away.

`evaluate` reports accuracy **per rule path** and names paths the gold set never
exercised as unevaluated. Do not quote its aggregate without the breakdown: a
run once scored 15/15 on stage and 8/8 on tissue while `skin` was mapped to
`pedal digit skin`, because every gold string happened to hit an exact label.

See `references/failure_catalogue.md` for the failures these rules exist to
prevent. Read it before changing any of them.
