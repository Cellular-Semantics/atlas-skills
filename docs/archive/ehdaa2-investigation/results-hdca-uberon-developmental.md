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
| B — no EHDAA2 label | 6 | 2 | the 84% case; both refutations unrepairable. Now superseded by the full-corpus sweep below |
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

## Full-corpus sweep (all 361 in-range pairs)

> **The sweep is not the route, and its numbers are not the route's numbers.**
> It implements steps 2-4 of the recipe — match a string into EHDAA2, read the
> bracket — and stops. It never crosswalks back to Uberon, so it never produces
> the thing a mapping is actually for, and it reads one string at a time with no
> access to sibling fields, study context or the rest of the record, which rung 0
> exists to make you read. A deliberately poor matcher, in other words. Treat the
> output as a coverage census plus a stress test of one step. The one number it
> cannot give is the method's false-positive rate.

`sweep-hdca-corpus.py` runs every in-range pair offline against the cached
authority. 557 atomic (stage, component) checks:

| outcome | checks |
|---|---|
| no EHDAA2 candidate found at all | 300 |
| candidate found, bracket does not refute | 208 |
| candidate found, **bracket refutes** | 47 |
| candidate found, no bracket asserted | 2 |

The 47 refutations are 31 distinct (component, stage, candidate) triples, and
sorting them by how the candidate was matched is the finding:

| match type | distinct refutations | sound |
|---|---|---|
| exact label | 5 | 5 |
| rung-2 substitution | 1 | 1 |
| substring / token overlap | 25 | 2 |

**The brackets were never wrong. The matches were.** Six of six refutations from
a principled match held up. Twenty-three of twenty-five from substring matching
were artefacts of a shared word — `Membrane` matching `anal membrane`, `stroma`
matching `corneal stroma mesenchyme`, `thoracic` matching `thoracic duct`.

The sharpest is `outflow tract` at CS14, matched to `outflow tract muscle`
(CS12-CS13) and "refuted". The term the annotator meant, `heart outflow`, is
CS12-open and would not have been refuted at all. A worse match manufactured a
confident refutation of a correct annotation.

So the refutations track match quality, not the brackets. Stated carefully:
**with this matcher**, restricting refutations to matches you would defend
leaves 6 of 6 standing, and allowing substring matches adds 25 of which 23 are
junk. That is an argument for the rule — a partial match generates candidates,
never refutations — and it is a real hazard for an agent too, which can also
make a sloppy match. It is not a measurement of what the skill does, because
the skill would not have made most of these matches.

`spine; thoracic` is the clearest demonstration that the matcher is the straw
man here. SKILL.md's rung 2 already gives this exact case as a worked example:
combine the fields, get `thoracic spine`, and land on
`UBERON:0006073 thoracic region of vertebral column` by exact synonym in one
lexical call, with no EHDAA2 and no graph. The sweep split the string, threw
`spine` away, matched the bare word `thoracic` to `thoracic duct`, and refuted
it. Same for `frontal` in a brain study, which is
`UBERON:0001870 frontal cortex` by label.

Two of the substring refutations are real: `knee joint` and `hip joint` at CS16
against the joint primordia, both CS19-. EHDAA2's plain `knee` and `hip` are
CS16- and in range, so the joint really does form later than the region. The
rule is not "never use substring" — it is "do not refute on one".

Splitting composites also turned out to be unsafe. `brain; stroma` means stroma
*of brain*, and `spinal cord; brachial` is the brachial spinal cord; the second
component is a modifier, not a second structure. Both spellings appear in the
corpus, which is how you can tell.

**Deterministic output matters here.** The first version of the sweep built its
variant list as a set, and Python randomises string hashing per process, so the
same string matched `exact` on one run and `substitution` on the next and the
headline table moved. Fixed to an ordered list, exact spellings first.

## Fetal coverage: there is none

Asked directly, the answer is a clean negative.

- Across all ~45 ontologies in Ubergraph there are **23** distinct
  existence-relation links to HsapDv, every one to a coarse stage
  (`prenatal stage`, `fetal stage`, `postnatal stage`). **None** points at the
  weekly fetal terms `HsapDv:0000046`-`0000075`.
- The older EHDAA is not served by OLS4 at all.
- EHDAA2 stops at CS20, about 7.5 pcw.

So past the embryonic period there is no stage-anchored anatomy resource
anywhere queryable, and the route has nothing to offer. The verifier now fails
if any weekly-fetal link ever appears, so we find out if that changes.

The same gap shows in Uberon's own precursor vocabulary: of the 247 terms named
with one of the seven precursor patterns, only **79 (32%)** carry an EHDAA2
xref. `X anlage` (12 terms) and `X rudiment` (2) have none at all; `presumptive
X` has 4 of 44, most of those being zebrafish- and frog-oriented. Two thirds of
the precursor vocabulary has no bracket available at any stage, embryonic
included.

## What this run cannot tell you

The brain supplies most of the exact-label matches, and
`braun_2023_brain` is 660 of 2606 rows. Tiers B and F are where the
generalisation risk sits, and six pairs is not enough to put a number on the
false-positive rate — only enough to say it is not obviously high. The next
useful run is a wider sweep of Tier B strings, which is cheap now that the
triage script exists.
