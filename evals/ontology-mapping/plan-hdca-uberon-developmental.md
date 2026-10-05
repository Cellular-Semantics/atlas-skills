# Plan: testing the EHDAA2 route against HDCA strings

Source: `HDCA_metadata/reports/embryonic_tissue_fields.csv`, 2642 rows.

## What the corpus actually offers

After dropping the 36 rows where `embryonic_call` is `rejected`:

| | rows |
|---|---|
| confirmed embryonic | 2606 |
| at or below CS20, so inside EHDAA2's range | 2407 (92%) |
| CS21-CS23, above the ceiling | 115 |
| `organogenesis stage`, no Carnegie stage at all | 84 |

Deduplicated to what actually needs testing: **361 distinct (stage, tissue)
pairs over 205 distinct tissue strings.** Testing rows would be testing the
same string eighty times; the pair is the unit.

The strings come in four shapes, and they are not equally interesting:

| shape | strings | example |
|---|---|---|
| plain | 175 | `liver`, `hindlimb`, `calvaria` |
| semicolon multi-tissue | 69 | `brain; heart; eye` |
| pipe-separated alternatives | 55 | `greatvessels \| heart \| mix` |
| single capitalised token | 62 | `Midbrain`, `Striatum` |

**Only 33 of 205 strings match an EHDAA2 label exactly.** That is the headline
finding of the triage and it reshapes the plan: the route as written leans on
step 3 (crosswalk from a Uberon lexical hit), but for 84% of real strings the
work is step 6 — searching EHDAA2's own vocabulary for what the region is
called at that stage. The test set has to be weighted accordingly.

## What a dry triage already found

Running every distinct string against the EHDAA2 windows offline, by exact
label match, three pairs are refuted by their bracket:

| string | observed | EHDAA2 window | note |
|---|---|---|---|
| `Mesencephalon` | CS15-CS19 | `EHDAA2:0000615` CS09-CS11 | EHDAA2 splits what Uberon merges |
| `medulla oblongata` | CS17 | `EHDAA2:0001088` CS18- | off by one stage |
| `spinal cord` | CS12 | `EHDAA2:0001255` CS13- | off by one stage |

Each is a different kind of result and all three are worth running properly.

`Mesencephalon` is the one to be careful about. EHDAA2 has *both*
`mesencephalon` (CS09-CS11) and `midbrain` (`EHDAA2:0001162`, CS12-), treating
them as different-time structures. Uberon makes them exact synonyms of
`UBERON:0001891`. So the bracket's "refutation" here is really EHDAA2 asserting
a vocabulary distinction Uberon does not recognise, and a skill that reports
"mesencephalon cannot exist at CS18" has said something false about the world
while correctly reading the ontology. **This is the most valuable case in the
set**, because it tests whether the route knows the difference between a
refutation and a naming convention. It is also the clearest candidate for a
false positive, which is the number this exercise most needs to produce.

The other two differ in how much the stage can be trusted. `spinal cord` at
CS12 comes from `xu_2023_embryo` with `stage_source_value = CS12` asserted
directly by the repository, confidence `high` — so the stage is not derived and
the disagreement is a real one about the tissue. `medulla oblongata` at CS17
comes from `braun_2023_brain` where the stage was converted from a decimal age
(`6.0`), verdict `SINGLE_SOURCE_OBS`, confidence `medium` — so the refutation
may indict the stage rather than the annotation. Those need different verdicts
and the test set should contain both.

## The subset: 21 pairs in six tiers

Chosen to span the decision space rather than to sample the corpus
proportionally. A proportional sample would be nine-tenths brain regions.

### Tier A — the bracket refutes (3)

`Mesencephalon` CS18 · `medulla oblongata` CS17 · `spinal cord` CS12

The reason the route exists. Tests that a refutation stops the mapping, that
the EHDAA2-vs-Uberon vocabulary split is recognised rather than parroted, and
that a low-confidence stage is weighed against the tissue rather than assumed
correct.

### Tier B — no EHDAA2 label, so step 6 (6)

`Medulla` CS19 · `Cortex` CS19 · `Striatum` CS19 · `Thalamus` CS18 ·
`mid vertebrae` CS16 · `calvaria` CS16

The 84% case. None matches an EHDAA2 label, so the route has to search EHDAA2's
vocabulary rather than crosswalk into it. `mid vertebrae` and `calvaria` are
the ones where the biology suggests a refutation the exact-match triage could
not see — at CS16 the vertebrae are sclerotome and the calvaria has not
ossified — so they test whether step 6 recovers the signal that step 3 missed.

### Tier C — bracket passes, candidate may still be wrong (4)

`liver` CS14 · `Heart` CS17 · `hindlimb` CS15 · `forelimb` CS16

All four pass their bracket. Tests the rule that a non-refuting bracket is not
an endorsement, and the limb pair tests the `RETIRED_` crosswalk again on real
strings rather than on my invented ones.

### Tier D — boundary (2)

`thymus` CS19 (EHDAA2 starts CS19) · `knee` CS16 (EHDAA2 starts CS16)

The observed stage is exactly the start bound. Tests whether the bound is read
as inclusive, which it is, and whether that is stated rather than assumed.

### Tier E — the route must not trigger (3)

`liver` at CS22 (above the CS20 ceiling) · a row with
`development_stage_label = organogenesis stage` (no Carnegie stage) ·
`UBERON:0002107 liver` (already a CURIE)

Three different reasons not to enter. Silence from EHDAA2 must not be read as a
negative result, a missing stage must stop the route rather than default it,
and an already-mapped value should not be re-derived.

### Tier F — strings the route was not designed for (3)

`brain; heart; eye` CS16 · `greatvessels | heart | mix` CS14 ·
`yolk sac; Membrane` CS10

A quarter of the corpus. These are multi-tissue and alternative-list strings,
and the honest expected outcome is that the route is applied per component or
declined, not that it returns one term. Included because leaving them out would
make the pass rate meaningless.

## How each case gets assessed

There is no gold standard, so the assessment is layered by what can be checked
mechanically and what cannot.

**Ontology facts — automated, already built.** Every CURIE, label, window, xref
and count asserted in the output is checked by
`verify-ehdaa2-claims.py` against the released OWL and Ubergraph. This layer is
deterministic and needs no judgement.

**Biology — manual, recorded per case.** Whether the structure really is
present at that stage is not something the ontology can settle. Latent
knowledge first, then a web search or the Wikipedia lookup for anything that
turns on a specific developmental timing, with the source recorded beside the
verdict. Where sources disagree with EHDAA2, that is a finding about EHDAA2 and
goes in the report rather than being resolved silently.

**Route behaviour — the actual pass criterion.** Per case: did it enter the
route when it should and stay out when it should not; did it refute correctly;
did it name a rival; did it flag the OLS4 end-bound hole where the term is one
of the 224 affected; did it report the EHDAA2 term it bridged through.

## The number this is really for

Not a pass rate. **The false-positive rate on refutations.**

A refutation that is wrong is worse than no route at all, because it tells a
curator to change a correct annotation. `Mesencephalon` shows the mechanism by
which that happens — EHDAA2 drawing a time distinction that Uberon treats as
synonymy — and nothing in the method as written detects it.

So the output of this exercise should be: of the refutations the route
produces across the 21 cases, how many survive scrutiny. If that number is poor,
the fix is in the reference text, probably a rule that a refutation must be
checked against whether the Uberon term treats the EHDAA2 term's label as a
synonym of a longer-lived term before it is reported.

## Risks

- **The stage column is not ground truth.** 1410 of 2606 rows are `medium`
  confidence and 358 are `CLASH`. A refutation may be a stage error. Tier A
  carries one of each deliberately; conclusions should not be drawn from
  `medium`-confidence rows alone.
- **The brain dominates.** `braun_2023_brain` is 660 rows and most of the
  interesting exact matches. Findings may not generalise to other organs, and
  the report should say which tier each conclusion came from.
- **224 terms carry the OLS4 hole.** If a test case lands on one, the result
  measures the bug rather than the method. Checked in advance: none of the nine
  named EHDAA2 terms in tiers A, C and D is affected, so the hole will not
  contaminate this run. Tier B terms are not known in advance, since finding
  them is the test — check each against the single-stage list when it turns up.

## Effort

Triage is already done and cost nothing. The 21 cases are the work: each is a
few `oq` calls plus a judgement, and the biology checks are the slow part. Call
it one sitting, with Tier A and Tier B worth doing first since they carry the
finding.
