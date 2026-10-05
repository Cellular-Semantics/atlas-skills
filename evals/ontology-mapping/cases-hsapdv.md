# Proposed gold-standard eval set: HsapDv developmental stages

**Status: proposed, not blessed.** Review and amend, then I will merge into the native `evals/cases/` harness.

33 cases. Every input string is taken verbatim from the HDCA `071_ontology_mapping` worktable, except `bare-number-with-units`, which reproduces a failure observed in real use. `n` = samples in that corpus carrying the string.

**Convention**: an integer week count is read as *N completed weeks* (UK clinical / ICD-10), unless the input is explicitly ordinal (`15th week …`), in which case it already names a term. Because an integer week is a rounded value with about half a week of slack, most such cases require the adjacent term to be named as a rival. A caller-stated convention overrides the default.

Every ID:label pair, label phrase and interval number was verified against live Ubergraph and the `.obo` from the OBO PURL. **no-call** cases expect a decline with reasons. *must mention* is a soft substring check over the report's prose, chosen so a correct answer cannot satisfy it by itself.


## A. Post-conception weeks

Cardinal integer weeks. Default to the UK clinical reading (N *completed* weeks), name the adjacent term, state the assumption. Includes the bare-number case, where the value carries no searchable text and the lexical rungs must be skipped.

### `pcw-20`  ·  n=70

**Input** `raw_stage` = `20 PCW`

**Expected** `HsapDv:0000058` — 21st week post-fertilization stage

The commonest input shape. 20 wpf = 140 dpf, which the 21st-week term spans [140,147). Answering the 20th-week term is the off-by-one failure: that term covers an age of 19-20 weeks.

*must name alternative: `HsapDv:0000057` — 20th week post-fertilization stage  ·  must mention: `over 20`*

### `pcw-10-boundary`  ·  n=27

**Input** `raw_stage` = `10 PCW`

**Expected** `HsapDv:0000048` — 11th week post-fertilization stage

70 dpf sits exactly on a boundary. Half-open intervals put it in the 11th-week term [70,77), not the 10th [63,70). Tests the boundary rule and the off-by-one together.

*must name alternative: `HsapDv:0000047` — 10th week post-fertilization stage  ·  must mention: `70`*

### `pcw-decimal-14-4`  ·  n=24

**Input** `raw_stage` = `late embryonic stage` + `raw_age` = `14.4 post-conception`

**Expected** `HsapDv:0000052` — 15th week post-fertilization stage

14.4 wpf = 100.8 dpf -> 15th-week term [98,105). Non-integer, so the 'in the Nth week' reading is unavailable and the off-by-one is tested cleanly. The 'late embryonic' label is wrong at 14 weeks and should be called out, not followed.

*must mention: `late embryonic`*

### `pcw-spelled-out`  ·  n=18

**Input** `raw_stage` = `embryo` + `raw_age` = `16 post-conceptional week`

**Expected** `HsapDv:0000054` — 17th week post-fertilization stage

Same arithmetic behind a different spelling. 16 wpf = 112 dpf -> 17th-week term. Checks that the unit is recognised without the 'PCW' abbreviation.

*must name alternative: `HsapDv:0000053` — 16th week post-fertilization stage*

### `bare-number-with-units`  ·  from observed failure

**Input** `raw_age` = `15` + `age_units` = `weeks post conception`

**Expected** `HsapDv:0000053` — 16th week post-fertilization stage

The value carries no searchable text. Observed failure: the agent read the ladder as 'always run rungs 1 and 2 on the raw input' and lexically searched '15', which cannot work -- no HsapDv label contains that digit -- and returns false leads with a rank attached. The information is in the sibling field, not the value: 15 completed weeks post conception = 105 dpf = the 16th week term. A correct run skips the lexical rungs, names age_units as what made it answerable, and verifies with `oq term`.

*must name alternative: `HsapDv:0000052` — 15th week post-fertilization stage  ·  must mention: `age_units`  ·  expected rung: 3*


## B. Gestational / LMP conversion

Subtract 2 weeks, then apply the same clinical reading.

### `gw-18`  ·  n=5

**Input** `raw_age` = `GW 18`

**Expected** `HsapDv:0000054` — 17th week post-fertilization stage

GW is last-menstrual-period weeks. 18 - 2 = 16 wpf = 112 dpf -> 17th-week term. Two conversions compose: LMP->pc, then age->ordinal. Skipping the first lands two terms late.

*must name alternative: `HsapDv:0000053` — 16th week post-fertilization stage  ·  must mention: `last menstrual`*

### `gestation-9wk`  ·  n=20

**Input** `raw_stage` = `embryo` + `raw_age` = `9 weeks gestation`

**Expected** `HsapDv:0000026` — Carnegie stage 19

9 LMP weeks = 7 wpf = 49 dpf, inside the embryonic period where only Carnegie stages exist -> CS19 [48,51). Composes the LMP conversion with the Carnegie branch.

*must name alternative: `HsapDv:0000025` — Carnegie stage 18; `HsapDv:0000027` — Carnegie stage 20*

### `gestational-age-23wk`  ·  n=2

**Input** `raw_stage` = `23 weeks gestational age`

**Expected** `HsapDv:0000059` — 22nd week post-fertilization stage

'gestational age' names the LMP convention explicitly. 23 - 2 = 21 wpf = 147 dpf -> 22nd-week term.

*must name alternative: `HsapDv:0000058` — 21st week post-fertilization stage*


## C. Sub-8-week — age to Carnegie

No weekly term exists before the 9th. Carnegie intervals are 1-5 days, so an integer week input reaches three or four stages: rivals matter most here.

### `carnegie-from-4wk`  ·  n=10

**Input** `raw_age` = `4wk`

**Expected** `HsapDv:0000020` — Carnegie stage 13

HsapDv has no weekly term before the 9th, so an embryonic age can only reach a Carnegie stage. 28 dpf -> CS13 [28,31). Must not invent a '4th week post-fertilization stage'.

*must name alternative: `HsapDv:0000019` — Carnegie stage 12; `HsapDv:0000021` — Carnegie stage 14  ·  must mention: `28`*

### `carnegie-from-5.7wk`  ·  n=21

**Input** `raw_stage` = `embryo stage` + `raw_age` = `5.7 week`

**Expected** `HsapDv:0000023` — Carnegie stage 16

39.9 dpf -> CS16 [37,42). Mid-interval, so unambiguous on days; still only approximate because Carnegie staging is morphological.

### `carnegie-pcw-no-space`  ·  n=1

**Input** `raw_age` = `PCW5.5`

**Expected** `HsapDv:0000023` — Carnegie stage 16

38.5 dpf -> CS16. Tests parsing a unit prefix with no separator.

### `carnegie-boundary-6wk`  ·  n=1

**Input** `raw_stage` = `embryo` + `raw_age` = `6 post-conceptional week`

**Expected** `HsapDv:0000024` — Carnegie stage 17

42 dpf is CS17's start and CS16's definitional comment ('day 37 to 42') also reaches it. The start_dpf partition resolves to CS17; a good answer names CS16 as the rival.

*must name alternative: `HsapDv:0000023` — Carnegie stage 16*

### `carnegie-hedged`  ·  n=1

**Input** `raw_age` = `about 4 PCW`

**Expected** `HsapDv:0000020` — Carnegie stage 13

Same arithmetic as carnegie-from-4wk, with an explicit hedge in the string. The term is unchanged; the hedge belongs in the confidence, not in a different answer.

*must name alternative: `HsapDv:0000019` — Carnegie stage 12; `HsapDv:0000021` — Carnegie stage 14*


## D. Explicit Carnegie strings

The stage is stated. No arithmetic, and it beats a conflicting age.

### `cs-compact`  ·  n=2

**Input** `raw_stage` = `CS14`

**Expected** `HsapDv:0000021` — Carnegie stage 14

'CS14' is an exact synonym on the term. Should finish at the cheapest rung without arithmetic.

*max rung: 1*

### `cs-prefixed-label`  ·  n=162

**Input** `raw_stage` = `embryonic stage / Carnegie stage 17`

**Expected** `HsapDv:0000024` — Carnegie stage 17

A Carnegie stage behind a redundant prefix. The prefix is not a second value to reconcile.

### `cs-plural-singular`  ·  n=28

**Input** `raw_stage` = `Carnegie Stages 13`

**Expected** `HsapDv:0000020` — Carnegie stage 13

'Stages' is plural but one value follows. Must not be read as a range.

### `cs-beats-age`  ·  n=9

**Input** `raw_stage` = `Carnegie stage 22` + `raw_age` = `8 week`

**Expected** `HsapDv:0000029` — Carnegie stage 22

Both fields are populated and disagree: 8 wpf = 56 dpf would give CS23 or the 9th-week term. The stated Carnegie stage is morphological and assigned from the specimen, so it wins - but the disagreement must be reported.

*must name alternative: `HsapDv:0000046` — 9th week post-fertilization stage  ·  must mention: `8 week`*

### `cs-range-15-16`  ·  n=68

**Input** `raw_stage` = `Carnegie Stages 15-16`

**Expected** **no-call**

A genuine two-stage range. No single Carnegie term is correct. Acceptable answers are an explicit no-call or the enclosing organogenesis stage; silently picking CS15 (as the lower) or CS16 (as the upper) is the failure.


## E. Obstetric weeks-plus-days

`8+3` is one age, not two — and precise, so a single term is right.

### `obstetric-8+3`  ·  n=1

**Input** `raw_age` = `8+3 PCW (post-conception wk)`

**Expected** `HsapDv:0000046` — 9th week post-fertilization stage

8 weeks 3 days = 59 dpf -> 9th-week term [56,63). The trap is reading '8+3' as two donors at 8 and 3 weeks, or as 8.3 weeks. All three readings give different answers.

*must not answer: `HsapDv:0000037` — fetal stage*

### `obstetric-14+4`  ·  n=1

**Input** `raw_age` = `14+4 PCW (post-conception wk)`

**Expected** `HsapDv:0000052` — 15th week post-fertilization stage

14 weeks 4 days = 102 dpf -> 15th-week term [98,105). Second W+D case because the notation is the single most under-recognised one in the corpus.


## F. Multi-value, ranges and ambiguous notation

No single term is correct, or two spellings are one donor.

### `multi-two-donors`  ·  n=21

**Input** `raw_stage` = `embryo stage` + `raw_age` = `5.8/7.6 week`

**Expected** **no-call**

Two donors, 40.6 and 53.2 dpf, i.e. CS16 and CS21. They share no week term; the lowest common ancestor is the organogenesis stage. Expected behaviour is a no-call naming both, not one of the two.

### `multi-three-pcw`  ·  n=2

**Input** `raw_stage` = `12, 14 and 19 PCW`

**Expected** **no-call**

Three donors spanning the 13th, 15th and 20th week terms. Lowest common ancestor is the fetal stage. Tests that a pooled row is recognised from prose ('and') rather than a delimiter.

### `range-tilde`  ·  n=3

**Input** `raw_age` = `9~11 week`

**Expected** **no-call**

A range, not a pool: 63 to 77 dpf, spanning the 10th, 11th and 12th week terms. Same no-call expectation; tests a '~' separator.

### `same-donor-two-notations`  ·  n=1

**Input** `raw_stage` = `7.4 PCW, 7/4 PCW`

**Expected** `HsapDv:0000027` — Carnegie stage 20 <br> or `HsapDv:0000028` — Carnegie stage 21

One donor written twice: '7.4 PCW' and '7/4 PCW' are the same 7-weeks-4-days value in two spellings, so this is NOT a two-donor row. 7w4d = 53 dpf -> CS21; a true decimal 7.4 = 51.8 dpf -> CS20. Either is acceptable if the reading is stated. The failure the corpus actually shows is pulling '4' out of '7/4' and answering CS13.

*must not answer: `HsapDv:0000020` — Carnegie stage 13*


## G. Field conflicts

Two populated fields implying different terms.

### `ordinal-label-plus-age`  ·  n=58

**Input** `raw_stage` = `15th week post-fertilization human stage` + `raw_age` = `15 week`

**Expected** `HsapDv:0000052` — 15th week post-fertilization stage

The label is HsapDv's own ordinal (14-15 wpf -> 15th-week term). The age read as 15 wpf would give the 16th-week term instead. The label is unambiguous and wins, but the one-term conflict must be surfaced - the corpus marks these high confidence with no review.

*must name alternative: `HsapDv:0000053` — 16th week post-fertilization stage  ·  must mention: `15 week`*

### `ordinal-label-bare-number`  ·  n=3

**Input** `raw_stage` = `10th week post-fertilization human stage` + `raw_age` = `12`

**Expected** `HsapDv:0000047` — 10th week post-fertilization stage

The label gives the 10th-week term directly. The bare '12' has no unit; if it is LMP weeks it implies 10 wpf and the 11th-week term. Answer from the label, flag the unit-less field.

### `label-contradicts-age`  ·  n=102

**Input** `raw_stage` = `late embryonic stage` + `raw_age` = `14 week`

**Expected** `HsapDv:0000052` — 15th week post-fertilization stage

The label is study-wide boilerplate and wrong (14 wpf is fetal); the age is per-sample. Take the age -> 98 dpf -> 15th-week term, and say the label disagrees.

*must name alternative: `HsapDv:0000051` — 14th week post-fertilization stage*

### `irreconcilable`  ·  n=2

**Input** `raw_stage` = `adult` + `raw_age` = `8 week`

**Expected** **no-call**

No human donor is both. One field is wrong or the age is on some other scale. Expected behaviour is a no-call that says what would settle it, not a best-effort term from either field.


## H. Days post conception

HsapDv's native unit. Precise, single term.

### `days-embryonic`  ·  n=4

**Input** `raw_stage` = `late embryonic stage` + `raw_age` = `47 day`

**Expected** `HsapDv:0000025` — Carnegie stage 18

47 dpf -> CS18 [44,48). Days are HsapDv's native unit, so no conversion is needed; the label agrees for once.

### `days-fetal`  ·  n=8

**Input** `raw_stage` = `late embryonic stage` + `raw_age` = `101 day`

**Expected** `HsapDv:0000052` — 15th week post-fertilization stage

101 dpf -> 15th-week term. Crosses out of the embryonic period, so the label is wrong. The corpus left this unmapped; the day count is enough to map it.


## I. Postnatal

Outside the reference note's prenatal scope; the corpus gets several wrong.

### `postnatal-years`  ·  n=2

**Input** `raw_stage` = `child stage` + `raw_age` = `10 year`

**Expected** `HsapDv:0000104` — 10-year-old stage <br> or `HsapDv:0000271` — juvenile stage (5-14 yo)

The exact age supports the 10-year-old stage; 'juvenile stage (5-14 yo)' is an acceptable coarser answer. Two traps: 'child stage (1-4 yo)' (HsapDv:0000265), which the corpus gives, excludes a 10-year-old; and '6-12 year-old child stage' (HsapDv:0000085) looks like a perfect fit but is obsolete, with HsapDv:0000271 as its replacement.

*must not answer: `HsapDv:0000265` — child stage (1-4 yo); `HsapDv:0000085` — 6-12 year-old child stage **(obsolete)***

### `postnatal-months-in-noise`  ·  n=4

**Input** `raw_stage` = `6months old human thymus`

**Expected** `HsapDv:0000179` — 6-month-old stage

The age is embedded in a string that also names a tissue. 6 months -> 6-month-old stage. Tests extraction without being derailed by 'thymus'.


## J. Out of scope

Not a human stage at all.

### `mouse-stage`  ·  n=2

**Input** `raw_stage` = `E8.5`

**Expected** **no-call**

Embryonic day 8.5 is mouse notation. HsapDv is human-only; the correct answer is a no-call that names MmusDv as the right ontology. Converting 8.5 days into a human Carnegie stage is the failure.

*must mention: `mouse`*


## Coverage

| bucket | cases | samples |
|---|---|---|
| A. Post-conception weeks | 5 | 139 |
| B. Gestational / LMP conversion | 3 | 27 |
| C. Sub-8-week — age to Carnegie | 5 | 34 |
| D. Explicit Carnegie strings | 5 | 269 |
| E. Obstetric weeks-plus-days | 2 | 2 |
| F. Multi-value, ranges and ambiguous notation | 4 | 27 |
| G. Field conflicts | 4 | 165 |
| H. Days post conception | 2 | 12 |
| I. Postnatal | 2 | 6 |
| J. Out of scope | 1 | 2 |
| **total** | **33** | **683** |
