# Refutation review: every bracket refutation on the HDCA corpus

Generated from `sweep-hdca-corpus.py`. The **verdict** column is a human judgement,
not a measurement — no ontology can settle it, and `verify-ehdaa2-claims.py` does not
guard it. It is recorded here so it can be disagreed with rather than inherited.

557 atomic (stage, component) checks produced 31 distinct refutations: 8 judged sound
(~50 rows), 23 judged wrong (~159 rows). Every refutation reached by an exact label
match or a stated substitution survived; 23 of the 25 reached by substring overlap did
not. That split is the evidence for the reference's rule that a partial match generates
candidates and never refutations.

`frag` marks a component that is not a whole annotation string but a piece left over
from splitting a composite such as `brain; stroma`.

## Judged sound — 8

| component | stage | matched via | EHDAA2 candidate | window | rows | reasoning |
|---|---|---|---|---|---|---|
| `Medulla` | CS17 | substitution | `EHDAA2:0001088` medulla oblongata | CS18-open | 12 | same finding as 'medulla oblongata'; reached by substitution, brain context from braun_2023_brain |
| `Mesencephalon` | CS15 | exact | `EHDAA2:0000615` mesencephalon | CS09-CS11 | 1 | EHDAA2 reserves 'mesencephalon' for the CS09-CS11 vesicle and uses 'midbrain' (CS12-) after; Uberon keeps the same split as presumptive midbrain / midbrain |
| `Mesencephalon` | CS18 | exact | `EHDAA2:0000615` mesencephalon | CS09-CS11 | 7 | EHDAA2 reserves 'mesencephalon' for the CS09-CS11 vesicle and uses 'midbrain' (CS12-) after; Uberon keeps the same split as presumptive midbrain / midbrain |
| `Mesencephalon` | CS19 | exact | `EHDAA2:0000615` mesencephalon | CS09-CS11 | 11 | EHDAA2 reserves 'mesencephalon' for the CS09-CS11 vesicle and uses 'midbrain' (CS12-) after; Uberon keeps the same split as presumptive midbrain / midbrain |
| `hip joint` | CS16 | substring | `EHDAA2:0000785` hip joint primordium | CS19-open | 3 | as knee joint |
| `knee joint` | CS16 | substring | `EHDAA2:0000897` knee joint primordium | CS19-open | 8 | joint primordium CS19- while plain 'knee' is CS16-; the joint does form after the region |
| `medulla oblongata` | CS17 | exact | `EHDAA2:0001088` medulla oblongata | CS18-open | 4 | the named structure does form after CS17; stage is medium-confidence from a decimal age, so the stage is the alternative explanation |
| `spinal cord` | CS12 | exact | `EHDAA2:0001255` spinal cord | CS13-open | 4 | repository-asserted CS12 at high confidence, so the stage is not in doubt; future spinal cord CS10-CS12 is the fit |

## Judged wrong — 23

| component | stage | matched via | EHDAA2 candidate | window | rows | reasoning |
|---|---|---|---|---|---|---|
| `Distal` | CS16 | substring | `EHDAA2:0001416` pars distalis | CS17-open | 4 | qualifier from 'hindlimb; Distal'; matched 'pars distalis' |
| `Membrane` `frag` | CS10 | substring | `EHDAA2:0004018` anal membrane | CS17-CS18 | 1 | fragment of 'yolk sac; Membrane'; means extraembryonic membrane, matched 'anal membrane' on one word |
| `Membrane` `frag` | CS11 | substring | `EHDAA2:0004018` anal membrane | CS17-CS18 | 1 | fragment of 'yolk sac; Membrane'; means extraembryonic membrane, matched 'anal membrane' on one word |
| `Membrane` `frag` | CS14 | substring | `EHDAA2:0004018` anal membrane | CS17-CS18 | 4 | fragment of 'yolk sac; Membrane'; means extraembryonic membrane, matched 'anal membrane' on one word |
| `Membrane` `frag` | CS15 | substring | `EHDAA2:0004018` anal membrane | CS17-CS18 | 5 | fragment of 'yolk sac; Membrane'; means extraembryonic membrane, matched 'anal membrane' on one word |
| `Proximal` | CS16 | substring | `EHDAA2:0004111` optic vesicle proximal part | CS12-CS13 | 4 | qualifier from 'forelimb; Proximal'; matched 'optic vesicle proximal part' |
| `Proximal` | CS17 | substring | `EHDAA2:0004111` optic vesicle proximal part | CS12-CS13 | 4 | qualifier from 'forelimb; Proximal'; matched 'optic vesicle proximal part' |
| `brachial` `frag` | CS14 | substring | `EHDAA2:0000181` brachialis | CS18-open | 1 | fragment of 'spinal cord; brachial' = brachial spinal cord; matched the muscle 'brachialis' |
| `brachial` `frag` | CS17 | substring | `EHDAA2:0000181` brachialis | CS18-open | 2 | fragment of 'spinal cord; brachial' = brachial spinal cord; matched the muscle 'brachialis' |
| `frontal` | CS16 | substring | `EHDAA2:0000577` frontal bone primordium | CS19-open | 2 | brain-study string, almost certainly frontal cortex; matched 'frontal bone primordium' |
| `gonad` | CS17 | substring | `EHDAA2:0000719` gonadal vein | CS19-open | 9 | matched 'gonadal vein'; the gonad itself is not refuted at these stages |
| `gonad` | CS18 | substring | `EHDAA2:0000719` gonadal vein | CS19-open | 2 | matched 'gonadal vein'; the gonad itself is not refuted at these stages |
| `lumbar` | CS15 | substring | `EHDAA2:0004502` lumbar sac | CS18-open | 2 | matched 'lumbar sac' |
| `membrane` | CS15 | substring | `EHDAA2:0004018` anal membrane | CS17-CS18 | 10 | as Membrane |
| `occipital` | CS16 | substring | `EHDAA2:0001283` occipital neural crest | CS10-CS13 | 2 | matched 'occipital neural crest' |
| `outflow tract` | CS14 | substring | `EHDAA2:0001358` outflow tract muscle | CS12-CS13 | 4 | matched 'outflow tract muscle' CS12-CS13; the intended 'heart outflow' is CS12-open and not refuted |
| `stroma` `frag` | CS16 | substring | `EHDAA2:0000318` corneal stroma mesenchyme | CS20-open | 79 | fragment of 'brain; stroma', i.e. stroma OF brain; matched 'corneal stroma mesenchyme' |
| `stroma` `frag` | CS17 | substring | `EHDAA2:0000318` corneal stroma mesenchyme | CS20-open | 16 | fragment of 'brain; stroma', i.e. stroma OF brain; matched 'corneal stroma mesenchyme' |
| `thoracic` | CS14 | substring | `EHDAA2:0004501` thoracic duct | CS18-open | 1 | fragment of 'spine; thoracic'; matched 'thoracic duct' |
| `thoracic` | CS15 | substring | `EHDAA2:0004501` thoracic duct | CS18-open | 2 | fragment of 'spine; thoracic'; matched 'thoracic duct' |
| `thoracic` | CS17 | substring | `EHDAA2:0004501` thoracic duct | CS18-open | 2 | fragment of 'spine; thoracic'; matched 'thoracic duct' |
| `yolk sac` | CS10 | substring | `EHDAA2:0002219` yolk sac stalk | CS14-open | 1 | matched 'yolk sac stalk'; the intended 'secondary yolk sac' is substage-anchored and brackets nothing |
| `yolk sac` | CS11 | substring | `EHDAA2:0002219` yolk sac stalk | CS14-open | 1 | matched 'yolk sac stalk'; the intended 'secondary yolk sac' is substage-anchored and brackets nothing |

## Open questions on these judgements

- **The two joint rows.** `knee joint` and `hip joint` are the only substring matches
  kept as sound, on the grounds that a joint forms later than the region around it:
  EHDAA2's plain `knee` and `hip` are CS16- and in range, the joint primordia CS19-.
  If that reasoning fails, the clean split between match types goes with it.
- **`frontal` at CS16** is called wrong from context — a brain study, so frontal cortex
  rather than frontal bone. That is inference, not data.
- **`Mesencephalon`** is sound in EHDAA2's terms, but it is the one case where the
  ontology's vocabulary may be narrower than an annotator's usage.

## What the sweep could not attempt

300 of the 557 checks found no EHDAA2 candidate at all — 107 distinct components,
~975 rows:

| kind | strings | rows | examples |
|---|---|---|---|
| positional / sectioning | 17 | ~472 | `lower vertebrae`, `section seven`, `whole sample` |
| named structures EHDAA2 lacks | 86 | ~365 | `calvaria`, `aorta-gonad-mesonephros`, `Thigh` |
| coarse / non-anatomical | 4 | ~138 | `internal organs`, `greatvessels`, `full reproductive tract` |

