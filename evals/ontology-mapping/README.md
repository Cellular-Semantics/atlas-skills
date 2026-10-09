# Ontology-mapping evals

These came in with the `onto-mapping` plugin and **use a different harness from
`evals/cases/`**. The native one in this repo is a directory per case with
`prompt.md` + `checks.json`, scored by `evals/runner.py` and `evals/graders.py`.
These are a single JSON file of cases scored by `check.py` beside them.

Converting them to the native format is outstanding work. Until then they run
on their own:

```
python evals/ontology-mapping/check.py <run-file.json>
```

`runner.py` globs `evals/cases/*`, so nothing here is picked up by the native
suite and nothing here interferes with it.

## What a report has to say

The skill reports which **moves** it made and which one produced the answer.
That replaced a single `rung` integer, which stopped having a referent when the
ladder became a funnel: Find is a menu selected by the last failure signal, so
"how far up did it go" is not a question about it any more.

The move names are a closed vocabulary in `moves.py`, kept in step with the
Stage 2 section headings in `SKILL.md`. A report or a case naming a move outside
it fails loudly, because drift between the two is otherwise silent and shows up
as a case that can never pass.

```
convert · exact · stemmed · alt-names · region · common-ancestors ·
relations · outside-ubergraph
```

A case can then express things a number could not: that the location query was
the whole point (`must_use: ["region"]`), or that reaching for the graph at all
was a failure of proportion (`must_not_use`, `max_moves`). The last of those
catches a run that gets the right term for too much money, which is a real
failure mode and used to be invisible.

## Files

- `cases-core.json` — 15 cases covering the skill's general behaviour: whether
  it triggers, which moves it makes, whether it names a rival.
- `moves.py` — the move vocabulary, shared by the cases and the scorer.
- `test_check.py` — tests for the scorer. It decides whether a run passed, so a
  bug in it either passes a bad run or fails a good one, and neither announces
  itself.
- `cases-hsapdv.json` — 32 developmental-stage cases, every input string taken
  verbatim from the HDCA `071_ontology_mapping` worktable. **Proposed, not yet
  blessed.**
- `cases-hsapdv.md` — the same 32 cases as a review document, with the
  reasoning for each expected answer spelled out. Read this one first.
- `verify-hsapdv-claims.py` — checks every HsapDv CURIE, ID:label pair, label
  phrase and interval number asserted in the skill text and the cases against
  the live ontology. Run it after editing `references/hsapdv.md`, after an
  HsapDv release, or whenever `oq release -o hsapdv` reports a move.

```
python evals/ontology-mapping/verify-hsapdv-claims.py            # live Ubergraph
python evals/ontology-mapping/verify-hsapdv-claims.py --offline  # cached
```

Needs an interpreter with CA certificates; Homebrew's python3 fails TLS here.

The EHDAA2 stage-bracket investigation that lived here has been withdrawn and
moved to `docs/archive/ehdaa2-investigation/` — record, not guidance. See its
README for why, and `docs/uberon-developmental-survey-brief.md` for what
replaces it.

## Two layers, both required

`packages/onto-query/tests` pins the query layer: the JSON envelope, the
guards, the promise that nothing scores or selects. These evals pin the
*skill's* behaviour — triggering, sequencing, interpretation, and whether the
report says the things that make an answer auditable. Neither substitutes for
the other.
