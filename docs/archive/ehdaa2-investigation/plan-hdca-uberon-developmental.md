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

Each is a different kind of result, and following them through changed the
plan.

**All three resolve, and none is a false positive.** I first read
`Mesencephalon` as EHDAA2 drawing a distinction Uberon treats as synonymy. That
was wrong. The crosswalk does not land on `UBERON:0001891 midbrain` — it lands
on **`UBERON:0009616 presumptive midbrain`**, a separate Uberon term defined as
"a presumptive structure that has the potential to develop into a midbrain",
with `has potential to develop into UBERON:0001891`. Uberon makes the same
distinction EHDAA2 does, and the xrefs keep the two apart correctly
(`EHDAA2:0001162 midbrain` xrefs `UBERON:0001891`). The refutation is sound and
the route recovers the right answer.

**Getting there needed Ubergraph, and a different edge each time.** EHDAA2's
own `develops_from` is empty in both directions on all three terms, so the
chain that finds the answer is Uberon's:

| annotation | edge | answer | answer's EHDAA2 window |
|---|---|---|---|
| `Mesencephalon` CS18 | `develops_from` `-d in` | `UBERON:0001891` midbrain | CS12- |
| `spinal cord` CS12 | `develops_from` `-d out` | `UBERON:0006241` future spinal cord | CS10-CS12 |
| `medulla oblongata` CS17 | `part_of` `-d out` | `UBERON:0005290` myelencephalon | CS16-CS17 |

`future spinal cord` closes at exactly CS12, and `myelencephalon` spans exactly
CS16-CS17. Both brackets land on the observed stage rather than merely
tolerating it, which is stronger evidence than this method usually produces.

The third row is the one that breaks a single-edge recipe:
`UBERON:0001896 medulla oblongata` has **no** `develops_from` in Uberon at all,
and the developmental relation is carried by `part_of myelencephalon`. A walk
that follows only `develops_from` returns nothing and reports the annotation
unmappable. Three cases, three edges — which is the argument for parameterised
edge sets rather than a bespoke command, and it is now in the reference with a
worked table and a checker that tests the logic rather than the prose.

**What this does to the plan.** Tier A has already been run, and all three pass.
The remaining value in Tier A is regression, not discovery, so the weight should
move to Tiers B and F. The false-positive question is still the right one, but
the three cases that looked most likely to produce one did not, so the estimate
has to come from the harder tiers rather than from these.

## The subset: 21 pairs in six tiers

Chosen to span the decision space rather than to sample the corpus
proportionally. A proportional sample would be nine-tenths brain regions.

### Tier A — the bracket refutes (3) — DONE

`Mesencephalon` CS18 · `medulla oblongata` CS17 · `spinal cord` CS12

All three run and all three resolve; see above. Keep them as regression cases,
since between them they exercise all three navigation edges, but they no longer
carry the finding. `medulla oblongata` is still worth revisiting against the
stage column: its CS17 is `medium` confidence converted from a decimal age, and
`myelencephalon` ending at CS17 means the mapping is right at the boundary.

### Tier B — no EHDAA2 label, so step 6 (6) — DO FIRST

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
produces across the 21 cases, how many survive scrutiny.

Tier A contributes three refutations and three survivals, which is encouraging
and not yet informative — those were the cases where an exact EHDAA2 label
existed, which is the easy 16%. The number that matters will come from Tier B,
where the term has to be found rather than matched, and from Tier F, where the
string does not name one structure at all.

## Risks

- **The stage column is not ground truth.** 1410 of 2606 rows are `medium`
  confidence and 358 are `CLASH`. A refutation may be a stage error. Tier A
  carries one of each deliberately; conclusions should not be drawn from
  `medium`-confidence rows alone.
- **A refutation can be a vocabulary split rather than an error.** Tier A
  showed Uberon and EHDAA2 agreeing, with `presumptive midbrain` kept separate
  from `midbrain` on both sides. That will not always hold, and where the
  crosswalk lands on a term whose label the annotator would consider a synonym
  of the one they wrote, the refutation needs checking before it is reported.
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
