# Archive: the EHDAA2 stage-bracket investigation

**This is a record, not guidance. Nothing here is live.** `uberon-developmental.md`
was a reference document for the `map-to-ontology` skill and has been withdrawn;
the skill no longer points at it. Do not follow its recipe without re-reading
the result below.

## What was tried

Map embryonic anatomy by going Uberon → EHDAA2 → read a Carnegie-stage existence
bracket → navigate if the stage is excluded → crosswalk back to Uberon. The
premise: annotators name the mature organ (`kidney`, `limb`, `lung`) on samples
where the thing present is its precursor, and no lexical probe can see that
error because the string matched a real term.

## Why it was withdrawn

The mechanism works. The yield does not justify it.

An independent systematic HDCA run — 38 mature terms, 167 candidates — accepted
**one** substitution (`embryo limb` at CS13 → `UBERON:0004347 limb bud`, which
is the same case this document used as its worked example). Of the 167:

| | n |
|---|---|
| samples all fetal, mature term already correct | 64 |
| no stage evidence on the candidate | 51 |
| precursor gone by the earliest sample | 27 |
| window overlapped, went to review | 25 |
| **accepted** | **1** |

54% out of scope because the samples are fetal or the precursor had closed —
EHDAA2 stops at CS20 (~7.5 pcw), which an embryonic-filtered sample set hides.

The deeper problem was method, not yield: we reached for a second ontology
before establishing what Uberon alone supports. `docs/uberon-developmental-survey-brief.md`
restarts from there.

## What is worth keeping from it

Three things were promoted out of here and are live:

- **The rung-2 word-substitution rule** in `SKILL.md`. Ontologies name one idea
  many ways and their own synonyms do not bridge the spellings — 9 of 39 Uberon
  `future X` terms carry `presumptive X`; 4 of 3161 GO `regulation of X` terms
  carry `control of X`.
- **`docs/onto-query-gaps.md`**, five `oq` changes. Item 1 is a genuine upstream
  OLS4 bug — its term-graph endpoint deduplicates edges by source and target, so
  a term asserting two predicates against the same target loses one. 224 EHDAA2
  classes lose their end bound this way and read as open-ended. Worth reporting
  to EBI regardless of whether we use EHDAA2 again.
- **The backend graph semantics** (`nonredundant` = direct, `redundant` =
  closure, `ontology` = OWL restrictions and useless to plain triple patterns),
  carried into the survey brief.

## Reading order, if you need the detail

1. `results-end-to-end.md` — 19 HDCA records worked whole-record to a Uberon
   CURIE. The most honest artefact here.
2. `results-hdca-uberon-developmental.md` — the corpus sweep and its limits.
3. `review-refutations.md` — per-refutation judgement, partly superseded by (1).
4. `uberon-developmental.md` — the withdrawn reference itself.
5. `plan-hdca-uberon-developmental.md` — how the test set was chosen.

## Known flaws in this work

Recorded because the testing went wrong in ways worth not repeating:

- `sweep-hdca-corpus.py` is a **deliberately dumb matcher** — one string at a
  time, no sibling fields, stops before crosswalking back to Uberon. Its numbers
  (47 refutations, "92% false positive") were reported as if they measured the
  method. They do not.
- The 19 end-to-end records were **selected because they were hard**, so 4-in-19
  is not a rate.
- `verify-ehdaa2-claims.py` scores 17/17 on mutation testing, but it verifies
  facts in a *document*. The skill's behaviour was never tested once.

## Running the scripts

They still work from here; paths were rewritten on archiving.

```
uv run docs/archive/ehdaa2-investigation/verify-ehdaa2-claims.py --offline --skip-ols4
uv run docs/archive/ehdaa2-investigation/mutate-ehdaa2-claims.py
uv run docs/archive/ehdaa2-investigation/sweep-hdca-corpus.py
```

`.ehdaa2-authority.json` is gitignored and rebuilt by the verifier without
`--offline`.
