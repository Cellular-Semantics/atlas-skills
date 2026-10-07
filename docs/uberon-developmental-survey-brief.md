# Brief: survey Uberon's developmental vocabulary

Starting document for a parallel session. Written so it can be picked up cold.

## Why this exists

We built a route for mapping embryonic anatomy that went Uberon → EHDAA2 for a
Carnegie-stage existence bracket → back to Uberon. It works, and it is not worth
much: an independent systematic HDCA run over 38 mature terms and 167 candidates
accepted **one** substitution. 54% of candidates were out of scope because the
samples are fetal or the precursor had already closed, and 31% had no stage
evidence at all. That investigation is archived under
`docs/archive/ehdaa2-investigation/` — **record, not guidance**.

The conclusion we drew: we reached for a second ontology before establishing
what Uberon itself supports. This survey fixes that order. **Uberon only.**

## What is already known — do not re-derive

**Backend mechanics.** Ubergraph holds three named graphs and the distinction
matters more than anything else here:

| graph | contains |
|---|---|
| `http://reasoner.renci.org/nonredundant` | **direct** asserted edges — this is what "direct `develops_from`" means |
| `http://reasoner.renci.org/redundant` | full transitive closure, including subsumption ancestors of relation targets, so it is noisy |
| `http://reasoner.renci.org/ontology` | OWL axioms as restrictions; a plain triple pattern returns **nothing** |

`oq relations` always answers from `redundant` and has no flag to change it; read
the first hop from `oq term` instead. `UBERON:0002240 develops_from` returns 1
term from `nonredundant` and 29 from `redundant`.

**Scale, measured 2026-10-07 against Uberon 2026-06-19:**

| | n |
|---|---|
| terms under `UBERON:0005423` developing anatomical structure (union with embryonic/presumptive structure) | 613 |
| of those, with a **direct** `develops_from` | 151 (25%) |
| terms named with a precursor pattern (`X primordium`, `X bud`, `presumptive X`, `future X`, `X anlage`, `developing X`, `X rudiment`) | 247 |

Note those two populations are **not** the same set, and reconciling them is one
of the survey's jobs — a term can be a developing structure without a precursor
name, and vice versa.

**Uberon's stage axioms are probably too weak to use.** Thousands of terms carry
`existence starts during or after` / `ends during or before`, but against
species-neutral life-cycle classes, and the commonest bounds are near-vacuous:

```
3348  starts during or after  gastrula stage
2253  starts during or after  neurula stage
2069  starts during or after  organogenesis stage
1716  ends during or before   post-embryonic stage
```

"Starts after gastrula stage" is true of almost everything. **Quantifying how
weak these are is a core deliverable**, because it is the evidence that decides
whether round two is needed at all.

**Naming is not reliable.** Only 9 of 39 `future X` terms carry the
`presumptive X` spelling as an exact synonym, and 9 of 44 the reverse. Generate
name variants; do not expect the ontology's synonyms to bridge them.

## Questions to answer

1. **What is the developmental vocabulary?** Reconcile the 613 structural
   population with the 247 naming population. How many terms are in one and not
   the other, and what does each exclusion look like? A term named
   `X primordium` that is not under `developing anatomical structure` is either
   a classification gap or a naming accident, and which it is matters.

2. **How informative are the stage bounds, term by term?** For each term with an
   existence bound, how far down the life-cycle hierarchy does the bound reach?
   A bound of `gastrula stage` carries no information; one of
   `organogenesis stage` carries a little. Produce a distribution, not a count.
   **This is the question that decides whether we need another ontology.**

3. **How well connected is `develops_from`?** 151 of 613 have a direct outward
   edge. The more useful question is the reverse: how many **mature** terms have
   a direct `develops_from` pointing at a developing structure? That is the
   relation an annotator's mature organ name has to traverse. Document the
   mature side first, then intersect with the 613 — that intersection is the set
   where this approach can work at all.

4. **Where are the holes?** Which common adult organs have no reachable
   developmental precursor in Uberon? Name them; that list is the honest
   statement of the method's ceiling.

5. **Which other relations carry developmental meaning?** `develops_from` is not
   the only one — `RO:0002207` develops from part of, `RO:0002225` develops from
   part of, `RO:0002254` has developmental contribution from,
   `has potential to develop into`, and `part_of` all did work in the archived
   investigation. One case there had **no** `develops_from` at all and the
   relation was carried by `part_of`. Survey which relations actually bear the
   load.

## Deliverable

A reference document under
`plugins/onto-mapping/skills/map-to-ontology/references/`, plus whatever
scripts produce its numbers. Shape it as findings first and advice second — the
archived document failed partly by being advice built on one worked example.

Every number in it should be reproducible by a committed script. Separate
**verified** facts from **judged** ones explicitly; conflating them is how the
last attempt overstated itself.

## Out of scope for round one

EHDAA2, EMAPA, and any cross-species bridge. Note where you hit a wall that a
second ontology would solve, but do not reach for one.

**Trigger for round two:** if question 2 shows Uberon's bounds cannot separate
embryonic from fetal for most terms. If that is the finding, the relevant fact
from the archived work is that **EMAPA is the stronger partner, not EHDAA2** —
it is in Ubergraph with full reasoning, has 4870 terms with start bounds and
3910 with end bounds against Theiler stages running to TS28 (newborn), and
xrefs 223 of the 613 developing structures. EHDAA2 is OLS4-only, stops at CS20
(~7.5 pcw), and xrefs 176.

## Gotchas

- EHDAA2 and EMAPA xrefs on retired classes hide under a `RETIRED_` prefix;
  `crosswalk EHDAA2:0003198` returns `[]` while `RETIRED_EHDAA2:0003198` resolves.
  Worth checking whether the same applies to anything you query.
- `oq term` on an ontology Ubergraph lacks returns an empty result with **no
  warning** — it looks like a term with no axioms. See `docs/onto-query-gaps.md`.
- Ubergraph 500s and drops connections on large aggregate queries; retry with
  backoff rather than concluding the data is absent.
- `purl.obolibrary.org` 500s intermittently on OWL fetches. Same advice.
