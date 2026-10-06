# End-to-end run: 19 HDCA records, whole record to Uberon CURIE

Each record was worked the way the skill says: read every field together first,
then candidate names, then lexical Uberon, then cross to EHDAA2 for a bracket,
navigate if refuted, crosswalk back, and emit a Uberon term with a reason.

Selected to span the tiers and to include every case the mechanical sweep got
interestingly wrong. 24 target strings collapsed to 19 distinct records, because
several strings live in the same record — which is itself the point: the unit is
the record, not the string.

225 of the 494 records carry an existing `worktable:tissue_term`. That is not a
gold standard — it is the curation this work exists to improve — but where the
run disagrees with it, the disagreement is a result either way.

## Outcome

| | |
|---|---|
| records worked | 19 |
| bracket refuted the first candidate | **3** |
| candidate had no EHDAA2 xref, so no bracket available | **11 of 23 terms** |
| answers differing from the existing curated term | 2 |
| records where the stage, not the tissue, is the problem | 4 |

Three refutations in 19 records, against 47 from the sweep. The difference is
entirely that a record read whole produces a defensible candidate, and a
defensible candidate is rarely refuted.

## The records

### Brain — `braun_2023_brain`, five records

**CS15, dissection `Mesencephalon`** → **`UBERON:0001891` midbrain**.
The record says `Region=Midbrain`, `Subregion=Midbrain`, `obs_tissue=midbrain`;
only the `dissection` field says Mesencephalon. Three fields against one settle
it before any ontology is touched. EHDAA2 midbrain is CS12- and in range.
*The sweep refuted this record by taking the one outlying field literally.*

**CS17, `Medulla` / `medulla oblongata`** → **`UBERON:0005290` myelencephalon**,
with `UBERON:0001896` medulla oblongata reported as the refuted first candidate.
EHDAA2 medulla oblongata starts CS18; `part_of` reaches myelencephalon, EHDAA2
CS16-CS17, which brackets the stage exactly. The stage is `medium` confidence
converted from `Age=6.0`, so the alternative reading — the stage is a stage late
— is in the report too.

**CS19, `Telencephalon` / `Cortex` / `Cortical hem` / `choroid plexus epithelium`**
→ **`UBERON:0003911` choroid plexus epithelium**, flagged.
Uberon has no `cortical hem`. The fields are not in conflict: the cortical hem
is the source of the choroid plexus, so a cortical hem dissection yielding
choroid plexus epithelium is coherent. The dissection *site* is unmappable and
the recovered *tissue* is not, so the tissue is what gets the CURIE and the gap
is recorded. No EHDAA2 xref, so no bracket.

**CS19, `Diencephalon` / `Thalamus` / `dorsal plus ventral thalamus`**
→ **`UBERON:0001897` dorsal plus ventral thalamus**.
`Thalamus` alone is ambiguous between the dorsal thalamus and the union;
`obs_tissue` states the union explicitly, so the record disambiguates itself. No
EHDAA2 xref, so no bracket — and the `ventral thalamus` / `subthalamus` xref
crossing never arises, because the union term is not reached through it.

**CS19, `Striatum`** → **`UBERON:0000369` corpus striatum**, rival
`UBERON:0002435` striatum. EHDAA2 calls its term `future corpus striatum`
(CS16-), in range, and that "future" is stated in the report: the ontology that
knows about the stage considers this a precursor.

### Skeletal — `to_2024_skeletal_integration`, three records

All three carry `stage_verdict=CLASH`, `confidence=low`, `needs_review=True`,
with the stage derived from `pcw=5.8`. **In all three the stage is the weaker
field**, and one record says so outright: `worktable:raw_tissue` reads
`mixture of hip at 7.3 pcw and knee at 8.6 pcw`. Neither of those ages is 5.8.

**CS16, `calvaria` + `bone=frontal`** → **`UBERON:0004339` vault of skull**,
refutation recorded. EHDAA2's `vault of skull` is CS19-, so CS16 is refuted, and
EHDAA2 offers nothing at CS16 to replace it — the mature-term fallback, exactly
as the rule says. `frontal` here is the **frontal bone**
(`UBERON:0000209` tetrapod frontal bone), not frontal cortex: the sibling field
is `anatomical_site=calvaria`. Given the stage is `low` confidence and disputed,
the refutation is reported as a reason to check the stage, not to change the
tissue.

**CS16, `knee`** → **`UBERON:0001465` knee**. EHDAA2 knee is CS16- and in range.
`UBERON:0001485` knee joint has **no EHDAA2 xref**, so the joint cannot be
bracketed at all through the proper route.

**CS16, `hip`** → **`UBERON:0001464` hip**, plus a data problem worth reporting:
this record's `anatomical_site` and `raw_tissue` both say hip, while
`E-MTAB-14385:Characteristics[organism part]` says **knee joint**. The
repository field contradicts the submitter's own annotation.

### Limb — `zhang_2023_limb`, three records

**CS15, `hindlimb` / `WholeLimb` / sampling site `hindlimb stylopod`**
→ **`UBERON:0002103` hindlimb**, flagged twice. EHDAA2 lower limb is CS13- and
in range, but `lower limb bud ectoderm` and `lower limb bud mesenchyme` run
CS13-**CS15**, so CS15 is the last stage at which this is a bud. And the
sampling-site field names the stylopod, which is more specific than the term
emitted.

**CS16, `forelimb` / region `Distal`** → **`UBERON:0002470` autopod region**,
fallback `UBERON:0002102` forelimb. The bud tissues ended at CS14, so at CS16
this is not a bud — the opposite of the CS13 case, and the bracket is what
distinguishes them.

**CS16, `forelimb` / region `Proximal`** → **`UBERON:0002472` stylopod**.
Neither limb-segment term has an EHDAA2 xref, so neither can be bracketed.

### Heart — `bayraktar_2024_heart`, two records

**CS14, region `outflow tract`** → **`UBERON:0004145` outflow tract**.
EHDAA2 `heart outflow` is CS12- and in range. *The sweep refuted this by
matching `outflow tract muscle` (CS12-CS13) instead — the single clearest case
of a bad match manufacturing a refutation.*

**CS22, region `whole sample`** → **`UBERON:0000948` heart**, route not entered.
CS22 is past the CS20 ceiling, so EHDAA2 has nothing to say and its silence is
not evidence. The field `heart_or_greatvessels = greatvessels | heart | mix` is
a list of the values used across the study, not this sample's content;
`obs_tissue = heart; whole sample` is what this sample is.

### Whole embryo — `webb_2026_embryo`, three records

**CS16, `lower vertebrae`** (six fields agreeing) →
**`UBERON:0001130` vertebral column**, the existing curated term, kept.
`UBERON:0001130` has no EHDAA2 xref, so no bracket. EHDAA2's stage-appropriate
vertebral terms — atlas and axis pre-cartilage condensations at CS15-CS16 — have
no Uberon xref either, so the route can see the right structure and cannot
express it. Mature-term fallback with the finding recorded.

**CS16, `internal organs`** → **`UBERON:0002075` viscus**, the curated term,
kept. Coarse but accurate; a `RETIRED_EHDAA2` xref only, so no bracket.

**CS16, `brain; heart; eye`** → **three terms, not one**: `UBERON:0000955` brain,
`UBERON:0000948` heart, `UBERON:0000970` eye. All three bracket in range
(EHDAA2 brain CS09-, eye CS10-). A composite naming three dissected structures
is three mappings; collapsing it to a common ancestor would lose what the record
actually says.

### Gonad — `garcia_alonso_2022_gonads`

**CS20, `gonad` / `Gonad_and_extragonadal`, female study**
→ **`UBERON:0000992` ovary**, where the curated term is `UBERON:0000991` gonad.

The best result in the run. `UBERON:0000991` has no EHDAA2 xref, so step 3
yields nothing and the route enters EHDAA2's own vocabulary at step 6. There,
`indifferent gonad` is CS15-**CS17** and `gonadal ridge` is CS14 only — both
refuted at CS20 — while `ovary` is CS18- and in range. The field name
`garcia_alonso_2022_gonads_female:location` supplies the sex. So at CS20 in a
female donor the structure is no longer an indifferent gonad, and the ontology
says so. **This is a real improvement on the existing curation, produced by the
bracket.**

### Spinal cord — `xu_2023_embryo`

**CS12, `spinal cord`** → **`UBERON:0006241` future spinal cord**, where the
curated term is `UBERON:0002240` spinal cord.

The stage is repository-asserted (`characteristics_ch1: developmental stage:
CS12`) at `high` confidence, so the stage is not the weak field here and the
disagreement is genuinely about the tissue. EHDAA2 spinal cord starts CS13;
`future spinal cord` is CS10-CS12 and closes exactly on the stage.

## What this says that the sweep could not

**Reading the record replaces most of the graph work.** `Mesencephalon` resolved
from three sibling fields. `Thalamus` resolved from `obs_tissue`. `frontal`
resolved from `anatomical_site`. `spine; thoracic` resolved by combining two
fields into `thoracic spine`, an exact Uberon synonym — which is SKILL.md's own
rung-2 worked example, and which the sweep failed by discarding `spine`.

**The bracket's real yield is small and specific.** Three refutations in 19
records, of which one changed the answer to something better (`ovary`), one
moved it to a neighbouring term (`myelencephalon`), and one could not be
repaired and fell back (`vault of skull`). Plus `future spinal cord`. That is
four records out of nineteen where EHDAA2 changed the outcome — a real but
modest contribution, and nothing like the impression the sweep's 47 refutations
gave.

**Missing xrefs limit the route more than missing brackets.** 11 of the 23
candidate terms had no EHDAA2 xref at all: knee joint, hip joint, thoracic
region of vertebral column, vertebral column, autopod region, stylopod, gonad,
striatum, dorsal plus ventral thalamus, choroid plexus epithelium, great vessel
of heart. For those the route is simply unavailable, whatever the stage.

**The stage is often the weaker field.** Four of the 19 records carry
`CLASH`/`low`/`needs_review`, and one states two ages in its own free text that
contradict the derived stage. A refutation on such a record is evidence about
the stage, not the tissue, and the report has to say which it is proposing to
change.

## Corrections to earlier claims

- **`frontal` at CS16 is the frontal bone**, not frontal cortex. I had marked
  the sweep's match wrong on the assumption it came from a brain study; the
  record says `anatomical_site=calvaria`, `bone=frontal`. My correction was
  itself wrong, and only reading the record showed it.
- **The two "sound" substring refutations do not survive.** `knee joint` and
  `hip joint` matched `knee joint primordium` and `hip joint primordium` in the
  sweep, but `UBERON:0001485` and `UBERON:0001486` have no EHDAA2 xref, so the
  proper route never reaches those terms and produces no bracket. Every
  surviving refutation now comes from an exact or substituted match, with none
  from substring — a cleaner split than claimed, reached by removing two of my
  own findings.
- **`mid vertebrae` at CS16 is not refuted by the route.** The refutation came
  from searching EHDAA2 directly; the terms it found have no Uberon xref, so
  there is nothing to crosswalk back. The outcome is the mature-term fallback,
  not a refutation.
