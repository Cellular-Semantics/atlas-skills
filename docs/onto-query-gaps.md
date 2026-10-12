# onto-query gaps found while building the EHDAA2 route

Five changes the reference doc currently works around. All are generic — a
parameter on an existing command, or a correctness fix — and none is specific
to developmental mapping. Listed worst first.

## 1. `neighbours` loses an edge when two predicates share a target

**Correctness bug, and it fails silently in the dangerous direction.**

`neighbours` reads OLS4's v1 term-graph endpoint, which deduplicates edges by
source and target. When a term asserts both `existence_starts_during_or_after`
and `existence_ends_during_or_before` against the *same* stage, one predicate is
discarded. `EHDAA2:0001570 pronephros` is CS09–CS09 in the released OWL and
reads as CS09-with-no-end through the tool.

224 EHDAA2 classes are affected — all of them, sampled — and they are the
single-stage transient structures, the ones that would refute a wrong mapping
most decisively. 39 are the per-somite terms. Through the tool they look
open-ended, so an annotation twenty stages too late passes.

**Fix**: read OLS4's v2 class endpoint instead. Its `relatedTo` array keeps both
restrictions with their `owl:onProperty` intact. Verified:

```
prop= BFO_0000050  value= EHDAA2_0001601
prop= RO_0002496   value= HsapDv_0000016
prop= RO_0002497   value= HsapDv_0000016
```

This is not EHDAA2-specific. Any ontology that asserts two predicates against
one target loses one of them.

## 2. `relations` answers only from the redundant graph

Ubergraph holds three graphs. For `UBERON:0002240 develops_from`:

| graph | edges |
|---|---|
| `nonredundant` | 1 — `posterior neural tube` |
| `redundant` | 29, mostly upper ontology |
| `ontology` | 0 — assertions are OWL restrictions, not triples |

`relations` always uses `redundant`, so the direct parent is buried in the
transitive closure along with `anatomical structure`, `blastula` and `embryo`.
The useful workflow is direct first, closure only when the direct edge leads
somewhere unusable.

**Fix**: `--graph nonredundant|redundant` (default `redundant` to preserve
behaviour), or `--direct` as sugar. Generic; nothing about this is
developmental.

## 3. `relations` hard-codes a six-predicate allowlist

`-p` accepts one of `develops_from, has_part, in_taxon, overlaps, part_of,
subClassOf`, one at a time. The existence predicates are not reachable at all,
and neither is anything else a caller might need.

**Fix**: accept any predicate CURIE, and make `-p` repeatable.

## 4. `neighbours` has no predicate filter, ontology restriction, or depth

It returns the whole one-hop neighbourhood and nothing else. Walking a chain
means repeated calls at OLS4 latency, and the caller does the bookkeeping.

**Fix**: repeatable `-p`, the `-t` target-ontology restriction `relations`
already has, and `--depth N` implemented as client-side BFS reporting the path.
OLS4 cannot give transitive ancestors over an arbitrary relation — the property
parameter on `hierarchicalAncestors` is silently ignored — so BFS in the package
is the only route. Branching is low enough to afford it: of 1862 EHDAA2 classes
with a `develops_from`, 1646 have exactly one parent and the maximum is five.

Keep the default shallow. These chains run back to `ectoderm` and
`inner cell mass`, and by hop three they stop being candidate generation.

## 5. `term` returns an empty result for an ontology Ubergraph lacks

`$OQ term EHDAA2:0002133 -o ehdaa2` returns
`{"annotations": {}, "relations": {}}` with no warning. That reads as a term
with no axioms rather than as a backend that does not hold the ontology.
`cohort` gets this right — it errors with "ehdaa2 is not in Ubergraph".

**Fix**: same error, or at minimum a warning.

## Note on what is *not* needed

An earlier draft proposed a `stage-window` command returning
`{start_bound, end_bound}`. It is not wanted. Once (3) lands, the existence
axioms fall out of a generic predicate query, and the interpretation — that the
bracket is one-sided, that it stops at CS20, that an absent end bound is silence
— belongs in the reference text where a reader can argue with it.
