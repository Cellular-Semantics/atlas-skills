# Proposal: widening onto-query without widening what it decides

Input to the `ladder-review` branch. Supersedes nothing; `docs/onto-query-gaps.md`
is the evidence base and is referenced by gap number throughout.

Status of every claim below: **verified** means a file and line is cited and I
read it. **judged** means I decided and the reasoning is here to argue with.
Nothing here has been measured against a live backend in this session.

## The line this draws

The library has two kinds of command and they want opposite treatment.

**Reporting commands** answer "what does the ontology say about this term I
have already chosen" — `term`, `relations`, `neighbours`, `xrefs`, `hierarchy`.
The caller has already made the judgement. The command fetches. There is no
ranking to corrupt, so restricting which predicate may be asked about buys
nothing and costs the whole RO vocabulary.

**Candidate-generating commands** answer "which terms should I be looking at" —
`lexical`, `common-ancestors`, `cohort`. These produce a set the caller did not
specify, and the result is interpretable *because* the scope is fixed. Common
ancestors' information content is comparable within a result set only, and only
because the traversal is the same for every row. Admitting an arbitrary
predicate would make the number mean nothing.

So: **liberalise the reporting commands, leave the generators alone.** The six
predicate names become a convenience alias table where they are currently an
`argparse` gate.

## What is actually restricted today (verified)

`PREDICATES` at `packages/onto-query/src/onto_query/ubergraph.py:45` is a
six-entry name→IRI map: `subClassOf, part_of, has_part, overlaps,
develops_from, in_taxon`. It is used as:

- `choices=sorted(PREDICATES)` on `relations -p`, single-valued — `cli.py:166`
- validation via `_pred()` for `common-ancestors --predicates` — `ubergraph.py:64`

`relations` hardcodes `GRAPH <{REDUNDANT_GRAPH}>` at `ubergraph.py:232`.
`neighbours` takes `curie` and `-o` and nothing else — `cli.py:283`.

Unreachable as a result: `connected_to`, `continuous_with`, `attaches_to`,
`innervates`, `located_in`, `develops_in`, `has_developmental_contributor`, the
existence predicates, and everything else in RO.

## The discovery loop is broken, which is the real bug

`term` already returns every predicate on the nonredundant graph, with labels
resolved (`ubergraph.py:273-286`). That is the natural way to find out what a
term carries. But it keys the result by the predicate **label** —
`r.get("plabel") or _short(r["p"])` at `ubergraph.py:282` — and never reports
the predicate's CURIE.

So even after `-p` accepts arbitrary CURIEs, a caller who sees
`"connected to": [...]` in `term` output has no identifier to pass to
`relations`. **Fixing `-p` without fixing `term` leaves the loop open.** These
two changes are one change. *(judged)*

---

## A. `relations`

**A1 — `-p` accepts any predicate CURIE.** `PREDICATES` becomes an alias table.
A value containing `:` is treated as a CURIE and passed through `to_iri`. A bare
word is resolved through the alias table, and an unrecognised bare word is still
an error naming the aliases — so `oq relations X -p part-of` fails usefully
rather than querying a nonexistent IRI. Retires gap 3.

**A2 — `-p` repeatable.** Result grows a `predicate` field per row and groups by
predicate. Breaking shape change; see versioning.

**A3 — `--graph nonredundant|redundant`,** default `redundant` to preserve
behaviour, with `--direct` as sugar for `nonredundant`. Retires gap 2. The
golden case is already measured in that document: `UBERON:0002240 develops_from`
gives 1 edge nonredundant, 29 redundant, 0 in the ontology graph.

**A4 — `--limit N` with truncation reported,** matching `lexical --rows` and
`cohort --limit`. An arbitrary predicate over the redundant graph can be large,
and silent truncation is the thing this library is careful about everywhere
else.

## B. `term`

**B1 — report predicate CURIE and label.** Change the relations block from
`{"<label>": [terms]}` to a list of
`{"predicate": "RO:0002170", "label": "connected to", "terms": [...]}`.
Closes the discovery loop described above. Breaking shape change.

**B2 — gap 5 needs a live check before anything is built.** The gaps document
says `term` returns an empty result with no warning for an ontology Ubergraph
lacks. `ubergraph.py:264-265` does append
`"<ont> is not in Ubergraph; asserted annotations unavailable"` when
`graph_for` returns `None`, and `cli.py:502` lifts that into the envelope. Gap 5
may already be closed, or may describe the *relations* half, which has no such
guard. **Unverified — run `oq term EHDAA2:0002133 -o ehdaa2` and look before
writing code.**

## C. `neighbours`

**C1 — read OLS4 v2 `relatedTo` instead of the v1 term graph.** This is a
correctness fix and the highest-value item in the whole proposal. The v1 graph
endpoint dedupes edges by source and target, so a term asserting two predicates
against one target loses one of them silently and in the dangerous direction —
`ols.py:296-307` buckets by `e.get("label")` per edge, but the endpoint has
already dropped the second edge before the tool sees it. Gap 1 reports 224
EHDAA2 classes affected, all sampled, and `Transport.ols4_v2_class` already
exists at `transport.py:72`. Retires gap 1.

**C2 — repeatable `-p` filter,** same alias-or-CURIE rule as A1.

**C3 — `-t` target-ontology restriction,** matching what `relations` already
has. C2 and C3 retire the first half of gap 4.

**C4 — `--depth N` as client-side BFS, reporting the path.** Default 1.
Affordable: gap 4 measured 1862 EHDAA2 classes with a `develops_from`, 1646 with
exactly one parent, maximum five. **Propose holding this back** — it is new
machinery and a new result shape, where C1–C3 are a backend swap and two filter
arguments. Separate decision, separate release.

---

## Not changing

- **`common-ancestors` predicates** — stays curated, per the correction that
  rung 3 is a tightly scoped candidate finder. Default `subClassOf, part_of`,
  still validated against the map. If more structural moves are wanted later,
  they arrive as new narrow commands, not as a free predicate on this one.
- **`lexical --probes`** — the three-probe set is the contract, not a limit.
- **`cohort` selectors** — substring-only `--label-contains`, no regex, no
  subtree restriction, no synonym search. Flagged as a gap; not proposed here.
  Open question below.
- **No raw-SPARQL escape hatch.** Nothing in the evidence calls for one, and it
  would put untestable queries in skill transcripts.

## Tests

All of it is cassette-replayable; re-record deliberately with
`tests/record_fixtures.py` and review the diff. New cases:

- an alias resolves to the same IRI the gate produced — golden, pins A1 as
  non-regressive
- a CURIE outside the alias table reaches the expected SPARQL
- an unrecognised bare word is still rejected
- `--graph nonredundant` returns one `develops_from` edge for `UBERON:0002240`
  where `redundant` returns 29
- repeatable `-p` groups rows by predicate
- `term` reports a predicate CURIE beside its label
- `neighbours` on `EHDAA2:0001570` keeps both `RO:0002496` and `RO:0002497`
  against `HsapDv:0000016` — the gap-1 regression test

`tests/test_contract.py:249 test_unknown_predicate_rejected` currently pins the
gate and must be rewritten to pin the alias rule instead.

## Versioning

`relations`, `term` and `neighbours` all change result shape, so this is
breaking: `0.2.0` → **`0.3.0`**, tagged `pkg-onto-query--v0.3.0`. `SKILL.md`'s
pin at `packages/onto-query` v0.2.0 and the surrounding text update in the same
commit, per the repo's rule that a contract change and every pinning skill move
together.

## Order of work

1. **C1** — silent wrong answers, nothing else in the proposal competes with it.
2. **A1 + A3 + B1** — the discovery→query loop, as one unit.
3. **A2, A4, C2, C3** — filters and limits.
4. **C4** — held back pending a decision.

## Open questions

1. **`relations` default graph.** Keep `redundant` so nothing changes, or flip
   to `nonredundant`? The skill text already says direct-first is the useful
   workflow, so the current default is arguably the wrong one — but flipping is
   a behaviour change on top of a shape change.
2. **C4 depth** — this release or its own?
3. **`cohort` selectors** — worth a gap entry now, or leave until a record needs
   one?
