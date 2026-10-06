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

## Files

- `cases-core.json` — 12 cases covering the skill's general behaviour: whether
  it triggers, how far up the ladder it goes, whether it names a rival.
- `cases-hsapdv.json` — 32 developmental-stage cases, every input string taken
  verbatim from the HDCA `071_ontology_mapping` worktable. **Proposed, not yet
  blessed.**
- `cases-hsapdv.md` — the same 32 cases as a review document, with the
  reasoning for each expected answer spelled out. Read this one first.
- `cases-uberon-developmental.json` — 10 embryonic-anatomy cases exercising the
  EHDAA2 route in `references/uberon-developmental.md`. **Proposed.** Every
  record but one is a real string from the HDCA `embryonic_tissue_fields`
  corpus; the exception is constructed, because no HDCA pair landed on a term
  affected by the OLS4 end-bound loss and that hole needs a regression case.
- `plan-hdca-uberon-developmental.md` / `results-hdca-uberon-developmental.md` —
  how the subset was chosen, and what running it found. The results are where
  the two bridge hazards and the extraembryonic blind spot came from; none was
  visible from invented examples.
- `verify-ehdaa2-claims.py` — checks every EHDAA2 CURIE, ID:label pair,
  existence window, xref pair, count and the CS20 ceiling asserted in the
  reference and the cases. Two authorities: the released EHDAA2 OWL for
  everything EHDAA2, Ubergraph for the xref bridge. It reads the OWL rather
  than OLS4 deliberately — OLS4 drops an `existence_ends_during_or_before`
  edge whenever it points at the same stage as the start edge, so a check
  written against OLS4 would confirm the reference's own worked examples to be
  wrong. It also tests for that data loss, so we find out when it is fixed.
- `sweep-hdca-corpus.py` — runs every in-range (stage, tissue) pair from the
  HDCA corpus through the EHDAA2 brackets, offline, and prints the refutations
  grouped by how the candidate was matched. Decides nothing; the grouping is
  what makes the output judgeable, and it is where the reference's "only refute
  on a match you would defend" rule came from. Output must be deterministic —
  an early version built its variant list as a set and the headline counts
  moved between runs.
- `mutate-ehdaa2-claims.py` — measures what the verifier catches, by breaking
  the reference seventeen ways and confirming each is caught. Currently
  **17/17**.
  Run it after editing either file; a drop means the verifier lost coverage.
- `verify-hsapdv-claims.py` — checks every HsapDv CURIE, ID:label pair, label
  phrase and interval number asserted in the skill text and the cases against
  the live ontology. Run it after editing `references/hsapdv.md`, after an
  HsapDv release, or whenever `oq release -o hsapdv` reports a move.

```
python evals/ontology-mapping/verify-hsapdv-claims.py            # live Ubergraph
python evals/ontology-mapping/verify-hsapdv-claims.py --offline  # cached

uv run evals/ontology-mapping/verify-ehdaa2-claims.py            # live
uv run evals/ontology-mapping/verify-ehdaa2-claims.py --offline --skip-ols4
uv run evals/ontology-mapping/mutate-ehdaa2-claims.py            # catch rate
```

`verify-hsapdv-claims.py` needs an interpreter with CA certificates; Homebrew's
python3 fails TLS here. The EHDAA2 pair carry inline metadata and pin `certifi`
themselves, so `uv run` is enough.

## Two layers, both required

`packages/onto-query/tests` pins the query layer: the JSON envelope, the
guards, the promise that nothing scores or selects. These evals pin the
*skill's* behaviour — triggering, sequencing, interpretation, and whether the
report says the things that make an answer auditable. Neither substitutes for
the other.
