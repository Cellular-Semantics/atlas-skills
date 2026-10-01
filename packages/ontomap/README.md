# ontomap

Map author-recorded **species, sex, developmental stage, disease and tissue**
strings onto ontology terms, for human single-cell atlases following the
CELLxGENE / HCA Tier 1 schema.

The governing constraint: **a wrong ontology id is worse than a missing one.**
It is plausible, it validates, it propagates, and nothing downstream questions
it. Every rule here either matches exactly, proves a structural claim, or
assigns nothing.

```sh
ontomap extract samples.csv --config config.json --out extracted.json
ontomap map     extracted.json --config config.json --out mapped.json
ontomap dossier mapped.json --config config.json --out dossiers.json
ontomap fold    mapped.json --judgements judgements.json --out folded.json
ontomap validate folded.json        # exit 2 on any failed gate
ontomap evaluate folded.json --gold gold.json
```

## Where the facts come from

| Source | Job |
|---|---|
| **Ubergraph** (SPARQL) | structure, axioms, closures, information content |
| **local label/synonym table** | exact, normalised and token-set matching, offline |
| **OLS search** | lexical candidates — never an assignment |
| **OLS lookup** | the validation gates, independently of what assigned the term |
| **EHDAA2** (vendored) | human stage windows for UBERON anatomy |

Validation deliberately asks a different service from the one that produced the
answer. Ubergraph is a periodic snapshot; if it both assigns and checks,
`LABEL_MATCHES` and `NOT_OBSOLETE` check nothing.

## Stage is numeric

HsapDv carries `start_dpf` / `end_dpf` on its Carnegie and week terms, so
`CS13`, `13 pcw`, `GW 15` and `92 days` all parse to a day and resolve against
the same windows — no conversion table between representations.

The chain that stages anatomy closes too:

```
UBERON --hasDbXref--> EHDAA2 --starts_at/ends_at--> HsapDv --dpf--> a day
```

1,835 UBERON terms carry an EHDAA2 xref; 2,444 of 2,459 EHDAA2 terms stage onto
HsapDv. So the same day that resolved the stage field decides whether a mature
organ term or its precursor is right.

## Vendored data

`src/ontomap/data/ehdaa2.json` and `hsapdv.json`, rebuilt by
`python tools/build_tables.py`.

EHDAA2 is **inactive but not obsolete** in OBO Foundry, frozen at
`releases/2024-01-11`. Inactive is not withdrawn: it is finished, which makes it
a pinned data dependency that cannot drift. It is also not loaded in Ubergraph —
its IRIs appear there only as dangling objects with no labels — so there is no
live structural route to it.

## Tests

```sh
pytest                # offline; no network
pytest -m live        # checks the structural assumptions against the real services
```

The live suite exists because this package rests on claims about someone else's
data. It is separate so a service outage cannot fail CI for an unrelated reason.
