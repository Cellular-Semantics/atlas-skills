# Results: the EHDAA2 route against HDCA strings

Run against `HDCA_metadata/reports/embryonic_tissue_fields.csv`, following
`plan-hdca-uberon-developmental.md`. All 21 pairs plus the three Tier A cases
already reported. Windows read from the EHDAA2 2024-01-11 OWL, xrefs from
Ubergraph `uberon-base` 2026-06-19, every assertion below re-checked by
`verify-ehdaa2-claims.py`.

## Headline

**The bracket refuted 6 of 21 pairs, and every refutation survived scrutiny.**
Zero false positives — which was the number this run existed to produce, so the
result is good but the sample is small and the brain is over-represented in it.

The more useful finding is where the value sits. The route almost never
overturns a lexical answer outright. What it does is **discriminate within a
series of near-identical strings**, which lexical matching structurally cannot.

## Tier by tier

| tier | pairs | refuted | notes |
|---|---|---|---|
| A — exact EHDAA2 label, refuted | 3 | 3 | all repaired by navigation, reported previously |
| B — no EHDAA2 label | 6 | 2 | the 84% case; both refutations unrepairable |
| C — bracket passes | 4 | 0 | but two needed sub-structure brackets to answer well |
| D — boundary | 2 | 0 | start bound read as inclusive, correctly |
| E — must not trigger | 3 | 0 | stayed out in all three |
| F — messy strings | 3 | 0 | declined to return one term, correctly |

## What the bracket is actually for

**The vertebral series is the best case in the corpus.** `to_2024_skeletal_integration`
carries `upper vertebrae`, `mid vertebrae`, `mid-low vertebrae` and
`lower vertebrae` at CS16 — four strings a lexical probe treats identically.
EHDAA2 has `atlas pre-cartilage condensation` and `axis pre-cartilage
condensation` at CS15-CS16, cervical cartilage condensations from CS17, and
thoracic from CS18. So at CS16 `upper vertebrae` has a candidate and
`mid vertebrae` does not. The bracket splits a family no string comparison can.

It also exposes the bridge's limit. `EHDAA2:0004004 axis pre-cartilage
condensation` and `EHDAA2:0004005 atlas pre-cartilage condensation` have **no
Uberon xref**, and Uberon has no such term to receive one. So the route
identifies the right structure and cannot express it: the best available answer
is the coarser `UBERON:0002413 cervical vertebra`, with the finding stated. The
route can be correct and still not produce a usable CURIE, and a report that
hides that behind a confident coarse mapping is worse than one that says so.

**The limb pair does the same in reverse.** `upper limb bud ectoderm` and
`upper limb bud mesenchyme` run CS12-CS14. So `forelimb` at CS13 is a bud and
`forelimb` at CS16 is not — and both stages are in the corpus. My invented
example had only the CS13 half, which made the rule look simpler than it is.

**`liver` at CS14 shows the same thing one level down.** Plain liver is CS12-
and passes. But `early liver parenchyma` is CS12-CS13 and `early liver hepatic
sinusoids` is CS13-CS13, so the sub-structure terms refute at CS14 while the
parent does not. A mapping to `UBERON:0002107` is right; a mapping to a liver
sub-structure needed the bracket to get right.

## Two refutations that cannot be repaired

`calvaria` at CS16 — `parietal bone primordium` and `interparietal bone
primordium` both start at CS19, and EHDAA2 has nothing at CS16 under any
cranial-vault name. `mid vertebrae` at CS16 fails the same way, and the
sclerotome terms that look like the obvious fallback ended at CS13-CS15.

Both are correct outcomes. The route's answer is "that structure does not exist
yet, and I cannot tell you what was dissected instead", and the temptation to
keep walking the chain until something fits is the thing to resist.

## Where the route is silent rather than useful

**Extraembryonic tissue.** `yolk sac` is the fourth commonest string in the
corpus, 72 rows at CS14-CS19. `EHDAA2:0002212 secondary yolk sac` xrefs
`UBERON:0001040 yolk sac` correctly, but its start bound is `HsapDv:0000033`
(CS05c), a Carnegie *substage* with no dpf, and it has no end bound. So the
bracket excludes nothing at any stage a sample carries. 57 EHDAA2 classes are
anchored this way and they cluster in exactly this branch — 10 yolk sac, 9
chorion, 8 trophoblast, 3 amnion.

This is silence, not a pass. A report that says `yolk sac` survived its bracket
has overstated what happened.

**Strings that do not name one structure.** `brain; heart; eye` at CS16,
`greatvessels | heart | mix` at CS14, `yolk sac; Membrane` at CS10. A quarter of
the corpus looks like this. The route applies per component or not at all.

## Two bridge hazards found by running real strings

**Matching labels are not matching terms.** `UBERON:0001900 ventral thalamus`
xrefs `EHDAA2:0004470 subthalamus`, while `EHDAA2:0004471 ventral thalamus` has
no Uberon xref at all. Crosswalking from the EHDAA2 term whose label matches
your string returns nothing; the Uberon term whose label matches lands on a
differently-labelled EHDAA2 term. Uberon carries "subthalamus" as an exact
synonym, so this is defensible rather than wrong, but it will mislead anyone
checking the bridge by eye.

**EHDAA2's "future X" collapses to Uberon's "X".**
`EHDAA2:0000234 future cerebral cortex` xrefs `UBERON:0000956 cerebral cortex`;
`EHDAA2:0000596 future corpus striatum` xrefs `UBERON:0000369 corpus striatum`.
Uberon has no "future" term to receive either. This is the opposite of
`presumptive midbrain`, where Uberon *did* keep the distinction — and nothing
distinguishes the two cases except looking.

Both hazards were invisible to the invented examples. They came out of
`Thalamus`, `Cortex` and `Striatum`, three strings I expected to be routine.

## The OLS4 bug, on real data

39 of the 224 terms that lose their end bound through OLS4 are the per-somite
terms. `somite 01` is CS09-CS09 in the OWL and CS09-with-no-end through
`neighbours`. A `somite` annotation at CS16 is refuted by seven stages and
would pass.

No tested pair landed on one, so the run was not contaminated. But the somite
terms are exactly what a somitogenesis study would annotate, and the corpus
already contains a positional vertebral series from the same tissue. This stops
being theoretical with the next dataset.

## What changed as a result

- The reference gained the corpus findings, the two bridge hazards, the
  substage/extraembryonic limit, and the rule that an unrepairable refutation is
  a result rather than a failure.
- `verify-ehdaa2-claims.py` gained checks for substage counts, the somite
  figure, and claimed *absences* — an absence rots quietly, because nothing else
  in the file contradicts it once upstream adds the xref.
- Mutation coverage went 8/8 → **15/15**.
- Six HDCA-derived eval cases replace six invented ones.

## Added after the run

Three things the run showed were missing, none of them specific to this route.

**Word substitution inside a name.** Uberon names developmental precursors
seven ways — `X primordium` (79 terms), `X bud` (63), `presumptive X` (44),
`future X` (39), `X anlage` (12), `developing X` (8), `X rudiment` (2) — and the
synonyms do not bridge them: only 9 of 39 `future X` terms carry the
`presumptive X` spelling. `future midbrain` returns nothing; `presumptive
midbrain` is the term. The general form is now in SKILL.md at rung 2, where it
belongs: in GO, 3161 terms are named `regulation of X` and exactly 4 carry a
`control of X` synonym, so a curator writing "control of glycolysis" finds
nothing by searching and finds it immediately by substituting one word.

**Direct edge before transitive closure.** `relations` answers from Ubergraph's
`redundant` graph. For `spinal cord develops_from` that is 29 terms; the
`nonredundant` graph has exactly one, `posterior neural tube`. Ask for the
direct parent first and only escalate when it leads somewhere without a
bracket — which is what happens here, since `posterior neural tube` has no
EHDAA2 xref. Read definitions when adjudicating the closure: `future spinal
cord` and `posterior neural tube` are equally plausible from their labels and
only one is dated.

**The mature-term fallback.** The run's original stance — an unrepairable
refutation returns nothing — was wrong for curation. A curator dissected
something and called it the calvaria, and that names a real region even though
the structure had not formed. The rule is now: if no stage-appropriate earlier
term can be found, emit the mature term with the refutation recorded beside it.
`calvaria` at CS16 maps to `UBERON:0004339 vault of skull`, flagged. The
refutation must reach the report, or the fallback becomes the same wrong answer
the route exists to catch.

`docs/onto-query-gaps.md` collects the five package changes these imply.

## What this run cannot tell you

The brain supplies most of the exact-label matches, and
`braun_2023_brain` is 660 of 2606 rows. Tiers B and F are where the
generalisation risk sits, and six pairs is not enough to put a number on the
false-positive rate — only enough to say it is not obviously high. The next
useful run is a wider sweep of Tier B strings, which is cheap now that the
triage script exists.
