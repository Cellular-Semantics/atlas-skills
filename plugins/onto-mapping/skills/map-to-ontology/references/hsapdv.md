# HsapDv: how developmental time is encoded

Reference for mapping human developmental stages given as days or weeks post
conception onto HsapDv terms.

Source: `http://purl.obolibrary.org/obo/hsapdv.owl`, release 2025-01-23
(`versionIRI .../releases/2025-01-23/components/hsapdv.owl`), 260 terms.
Everything below was read off that release.

## This file is a cached index, not the authority

The ontology is the authority and it gets corrected. The interval table at the
bottom is here so you can find a candidate in one step instead of making fifty
queries; it is not evidence.

**First, check whether this file is still describing the live ontology:**

```
$OQ release -o hsapdv --expect 2025-01-23
```

`matches_expected: true` means the backends serve the release this file was
written against, and the table below can be trusted as a shortcut. False means
HsapDv has moved: the prose here is still a good guide to *how* time is
encoded, but re-derive any specific interval you rely on, and say in your
report that the reference was stale. The check is cached by date, so it costs
nothing after the first call of the day.

**Then confirm the term you land on, whatever the release says:**

```
$OQ term <CURIE> -o hsapdv
```

Ubergraph holds the hsapdv asserted graph and `term` returns its literal
annotations, `start_dpf` and `end_dpf` among them. If the returned interval
does not contain your value, the live ontology wins — use it, and say in your
report that this reference was stale.

Near an interval boundary, query the neighbouring term too. That is the case
where a small correction upstream changes the answer.

There is no range query. No command takes a number and returns the term whose
interval contains it, and `cohort --label-contains "week post-fertilization"`
enumerates the thirty weekly terms but returns labels only. Hence the cached
table.

## Where the numbers live

Temporally anchored prenatal terms carry two OBO annotation properties:

- `start_dpf` — start, **days post fertilization**, `xsd:float`
- `end_dpf` — end, days post fertilization

These are the only machine-readable time anchors in the prenatal branch. There
is no OWL logical axiom encoding the intervals, so mapping an age to a term is
an interval lookup, not a reasoning problem. Postnatal terms use `start_ypb` /
`end_ypb` and `start_mpb` / `end_mpb` instead, which are out of scope here.

The prenatal span is 0–266 dpf (`HsapDv:0000045` prenatal stage), split at
56 dpf into `HsapDv:0000002` embryonic stage (0–56) and `HsapDv:0000037` fetal
stage (56–266).

Structure is carried by `part_of`, not `is_a` — nearly every term is
`is_a HsapDv:0000000` (life cycle stage) and the real hierarchy is the
`part_of` chain. There are also `immediately_preceded_by` chains and
`has_stage_marker` links to EHDAA2 / UBERON / GO landmarks.

## Two granularity systems, split at 8 weeks

**0–8 weeks post conception: Carnegie stages only.** There are no
"week post-fertilization" terms for weeks 1–8. CS01–CS23 each have a
`start_dpf` but **no `end_dpf`** — the end has to be derived from the next
stage's start. The intervals are unequal: CS05 spans 7–13 dpf, CS21 spans
53–54 dpf.

**8–38 weeks post conception: weekly terms.** `HsapDv:0000046`–`HsapDv:0000075`,
each with both `start_dpf` and `end_dpf`, exactly 7 days wide, grouped under
coarser "LMP month" parents (`HsapDv:0000197`–`HsapDv:0000203`).

## The off-by-one trap

The single most likely source of a wrong mapping:

> `HsapDv:0000046` — label "**9th** week post-fertilization stage", definition
> "Fetal stage when the fetus is over **8** and under **9** weeks of
> development", `start_dpf 56`, `end_dpf 63`.

The label is an ordinal week number; the age it denotes is one less. So:

- "10 pcw" → 70 dpf → **11th** week post-fertilization stage (`HsapDv:0000048`)
- "19 pcw" → 133 dpf → **20th** week post-fertilization stage (`HsapDv:0000057`)

Matching the integer in the input against the integer in the label is
systematically one stage too early. Convert to dpf first, then look up the
interval.

## Reading the input before converting it

Four notations turn up often enough in archive metadata to be worth naming.
Getting the *reading* wrong costs more than getting the lookup wrong, because
the lookup is then confidently applied to the wrong number.

**`W+D` — obstetric weeks-plus-days.** `8+3 PCW`, `13+2`, `14+4` are a single
age written as whole weeks plus loose days: `8+3` is 8 weeks 3 days = 59 dpf,
*not* two values of 8 and 3, and not 8.3 weeks. Splitting it on the `+` and
treating it as a multi-donor range is the common failure. The days part is
always 0-6, so a second number above 6 means you are looking at something else.
A `W/D` spelling (`7/4 PCW`) and a bare decimal in the same field (`7.4 PCW`)
usually mean the same thing: many studies write 7 weeks 4 days as "7.4". When
the same row carries both spellings, it is one donor written twice, not two.

**A decimal that may not be a decimal.** `7.4 week` is 7.4 × 7 = 51.8 dpf if it
is a true decimal, and 53 dpf if the author meant 7 weeks 4 days. Those are
adjacent Carnegie stages. Decide which the study means — a column of values
whose fractional parts never exceed `.6` is weeks-plus-days, not decimals —
and say which reading you used.

**An input that already states an HsapDv ordinal.** `10th week
post-fertilization human stage` is the ontology's own label with a word added.
Use the term directly; do not read "10" as an age and convert it again, which
lands you one term late.

**Integer `N PCW`.** Default to the **UK clinical convention**: `N weeks`
means *N completed weeks*, i.e. elapsed time in `[N, N+1)`. ICD-10 states it
explicitly — "36 completed weeks" spans 36+0 to 36+6, and preterm is "28
completed weeks or more but less than 37 ... 196 completed days but less than
259" — and RCOG and NICE guidance is written in `W+D` throughout. So
`12 PCW` = 84 dpf = **13th week post-fertilization stage** (`HsapDv:0000050`).

Override that default in one case: when the input is **explicitly ordinal**
(`15th week post-fertilization human stage`, `the 15th week`), it already names
a HsapDv term. Use that term and do not convert.

**Always name the adjacent term, and always state the assumption.** An integer
week count is a rounded value carrying roughly half a week of slack, so it is
compatible with two neighbouring week terms — and in the embryonic period,
where Carnegie intervals are 1-5 days, with three or four Carnegie stages
(`4wk` reaches CS11 to CS14). A report that gives one term without naming the
neighbour and the convention used is overstating what the string supports.
Never mark a bare integer week input as high confidence.

Evidence for the slack, in case it is ever questioned: in E-MTAB-11278 (an
HDBR-sourced study) the embryonic samples pair an HDBR morphological Carnegie
stage against the recorded pcw integer — 5 pcw/CS14, 6 pcw/CS17, 8 pcw/CS22.
Only round-to-nearest fits all three; completed-weeks fits one of three. The
fetal rows in the same study cannot settle it, because their
`developmental stage` column is the submitter's own number-matched annotation
of their own `age` column.

**A stated preference wins over all of this.** If the record, the dataset
documentation, or the person asking names a convention, use theirs and say so.
Where a convention is given for one field, do not silently extend it to
another.

## When two fields disagree

Records often carry both a stage label and an age, and they routinely imply
different terms — a label reading `late embryonic stage` beside an age of
`14 week`, or an ordinal label beside a bare number that looks like LMP weeks.

Do not silently prefer one. Work out what each field implies on its own, then:

- **An explicit Carnegie stage beats an age.** Carnegie staging is
  morphological and was assigned by someone looking at the specimen; the age is
  usually derived. Where a study states Carnegie stages anywhere, use them.
- **A specific value beats a study-wide label.** `late embryonic stage`
  repeated identically across every sample in a study carries no per-sample
  information; a per-sample age does. Take the age, and note that the label
  disagrees.
- **A disagreement of one term is still a disagreement.** It usually means the
  two fields use different conventions (LMP against post-conception). Report
  it; do not average it away or let it pass as high confidence.
- **An irreconcilable pair is not a mapping.** `adult` beside `8 week` cannot
  both be true of a human donor. Return no term and say what would settle it.

## Other things that will bite

- **Intervals are half-open `[start, end)`.** A value exactly on a boundary
  belongs to the later term: day 70 is the 11th week, not the 10th.
- **56 dpf is double-covered.** `Carnegie stage 23` has `start_dpf 56` (its
  comment says "day 56 to 60") while fetal stage and the 9th-week term also
  start at 56. For an 8-pcw sample prefer the week term when the source is
  reporting age, the Carnegie term when it is reporting morphology.
- **Carnegie days are approximate.** The `start_dpf` values form a clean
  non-overlapping sequence, but the definitional comments overlap — "CS13
  usually starts between day 28 and day 32". Carnegie staging is morphological
  and the days are indicative. If a record states a Carnegie stage directly,
  use it; do not round-trip through days.
- **LMP vs post-conception.** Prenatal stage ends at 266 dpf = 38 weeks post
  conception = 40 weeks LMP. Gestational age by last menstrual period is
  conventionally pcw + 2. Check which convention a source means before
  converting: getting it wrong moves the mapping by two terms. The "LMP month"
  terms are named on the LMP convention while the weekly terms are named on the
  post-fertilization convention, so the two naming systems in this ontology do
  not agree with each other.
- **The terminal term is open-ended.** `HsapDv:0000075` is "38th week
  post-fertilization **and over** stage", so anything ≥ 259 dpf lands there.
- **Substages have no times.** CS05a/b/c and CS06a/b (`HsapDv:0000031`–`0000035`)
  carry no dpf annotations at all. They are morphological only and cannot be
  reached from an age.
- **Useful synonyms.** Carnegie terms carry exact synonyms `CS01`…`CS23`, worth
  matching against free-text metadata. Two data errors in this release:
  `HsapDv:0000009` (Carnegie stage 05) carries the synonym "CS04", and
  `HsapDv:0000082` "newborn stage " has a trailing space in its label.
- **Obsoletes.** The postnatal branch has several obsoleted terms with
  `replaced_by` / `consider`. Check `is_obsolete` before emitting any HsapDv
  CURIE taken from an older mapping.

## Recipe

1. Normalise the input to days post fertilization. Subtract 14 days if the
   source gives LMP / gestational age.
2. If dpf < 56, look up the Carnegie interval and return that term. Record in
   the report that the age-to-Carnegie mapping is approximate.
3. If 56 ≤ dpf < 266, look up the weekly interval, treating it as
   `[start, end)`.
4. If the input is a range spanning more than one term, return the lowest
   common `part_of` ancestor — an LMP month term, or fetal stage / embryonic
   stage — rather than picking one week arbitrarily.
5. Confirm the candidate with `$OQ term <CURIE> -o hsapdv` and check that the
   returned `start_dpf`/`end_dpf` really do bracket your value. If the value
   sits within a day or two of a boundary, query the neighbour as well.

## Interval table

Cached from the 2025-01-23 release — see the note at the top, and confirm the
term you pick with `$OQ term`.

`end_dpf` for Carnegie stages is derived from the next stage's `start_dpf`
(CS23's end is taken from its definitional comment, day 60). Weekly rows use
the asserted `end_dpf`. Treat every interval as `[start, end)`.

| start_dpf | end_dpf | start_pcw | end_pcw | id | label |
|---|---|---|---|---|---|
| 0.0 | 2.5 | 0.00 | 0.36 | HsapDv:0000003 | Carnegie stage 01 |
| 2.5 | 4.5 | 0.36 | 0.64 | HsapDv:0000005 | Carnegie stage 02 |
| 4.5 | 5.5 | 0.64 | 0.79 | HsapDv:0000007 | Carnegie stage 03 |
| 5.5 | 7.0 | 0.79 | 1.00 | HsapDv:0000008 | Carnegie stage 04 |
| 7.0 | 13.0 | 1.00 | 1.86 | HsapDv:0000009 | Carnegie stage 05 |
| 13.0 | 15.0 | 1.86 | 2.14 | HsapDv:0000011 | Carnegie stage 06 |
| 15.0 | 17.0 | 2.14 | 2.43 | HsapDv:0000013 | Carnegie stage 07 |
| 17.0 | 19.0 | 2.43 | 2.71 | HsapDv:0000014 | Carnegie stage 08 |
| 19.0 | 22.0 | 2.71 | 3.14 | HsapDv:0000016 | Carnegie stage 09 |
| 22.0 | 23.0 | 3.14 | 3.29 | HsapDv:0000017 | Carnegie stage 10 |
| 23.0 | 26.0 | 3.29 | 3.71 | HsapDv:0000018 | Carnegie stage 11 |
| 26.0 | 28.0 | 3.71 | 4.00 | HsapDv:0000019 | Carnegie stage 12 |
| 28.0 | 31.0 | 4.00 | 4.43 | HsapDv:0000020 | Carnegie stage 13 |
| 31.0 | 35.0 | 4.43 | 5.00 | HsapDv:0000021 | Carnegie stage 14 |
| 35.0 | 37.0 | 5.00 | 5.29 | HsapDv:0000022 | Carnegie stage 15 |
| 37.0 | 42.0 | 5.29 | 6.00 | HsapDv:0000023 | Carnegie stage 16 |
| 42.0 | 44.0 | 6.00 | 6.29 | HsapDv:0000024 | Carnegie stage 17 |
| 44.0 | 48.0 | 6.29 | 6.86 | HsapDv:0000025 | Carnegie stage 18 |
| 48.0 | 51.0 | 6.86 | 7.29 | HsapDv:0000026 | Carnegie stage 19 |
| 51.0 | 53.0 | 7.29 | 7.57 | HsapDv:0000027 | Carnegie stage 20 |
| 53.0 | 54.0 | 7.57 | 7.71 | HsapDv:0000028 | Carnegie stage 21 |
| 54.0 | 56.0 | 7.71 | 8.00 | HsapDv:0000029 | Carnegie stage 22 |
| 56.0 | 60.0 | 8.00 | 8.57 | HsapDv:0000030 | Carnegie stage 23 |
| 56.0 | 63.0 | 8.00 | 9.00 | HsapDv:0000046 | 9th week post-fertilization stage |
| 63.0 | 70.0 | 9.00 | 10.00 | HsapDv:0000047 | 10th week post-fertilization stage |
| 70.0 | 77.0 | 10.00 | 11.00 | HsapDv:0000048 | 11th week post-fertilization stage |
| 77.0 | 84.0 | 11.00 | 12.00 | HsapDv:0000049 | 12th week post-fertilization stage |
| 84.0 | 91.0 | 12.00 | 13.00 | HsapDv:0000050 | 13th week post-fertilization stage |
| 91.0 | 98.0 | 13.00 | 14.00 | HsapDv:0000051 | 14th week post-fertilization stage |
| 98.0 | 105.0 | 14.00 | 15.00 | HsapDv:0000052 | 15th week post-fertilization stage |
| 105.0 | 112.0 | 15.00 | 16.00 | HsapDv:0000053 | 16th week post-fertilization stage |
| 112.0 | 119.0 | 16.00 | 17.00 | HsapDv:0000054 | 17th week post-fertilization stage |
| 119.0 | 126.0 | 17.00 | 18.00 | HsapDv:0000055 | 18th week post-fertilization stage |
| 126.0 | 133.0 | 18.00 | 19.00 | HsapDv:0000056 | 19th week post-fertilization stage |
| 133.0 | 140.0 | 19.00 | 20.00 | HsapDv:0000057 | 20th week post-fertilization stage |
| 140.0 | 147.0 | 20.00 | 21.00 | HsapDv:0000058 | 21st week post-fertilization stage |
| 147.0 | 154.0 | 21.00 | 22.00 | HsapDv:0000059 | 22nd week post-fertilization stage |
| 154.0 | 161.0 | 22.00 | 23.00 | HsapDv:0000060 | 23rd week post-fertilization stage |
| 161.0 | 168.0 | 23.00 | 24.00 | HsapDv:0000061 | 24th week post-fertilization stage |
| 168.0 | 175.0 | 24.00 | 25.00 | HsapDv:0000062 | 25th week post-fertilization stage |
| 175.0 | 182.0 | 25.00 | 26.00 | HsapDv:0000063 | 26th week post-fertilization stage |
| 182.0 | 189.0 | 26.00 | 27.00 | HsapDv:0000064 | 27th week post-fertilization stage |
| 189.0 | 196.0 | 27.00 | 28.00 | HsapDv:0000065 | 28th week post-fertilization stage |
| 196.0 | 203.0 | 28.00 | 29.00 | HsapDv:0000066 | 29th week post-fertilization stage |
| 203.0 | 210.0 | 29.00 | 30.00 | HsapDv:0000067 | 30th week post-fertilization stage |
| 210.0 | 217.0 | 30.00 | 31.00 | HsapDv:0000068 | 31st week post-fertilization stage |
| 217.0 | 224.0 | 31.00 | 32.00 | HsapDv:0000069 | 32nd week post-fertilization stage |
| 224.0 | 231.0 | 32.00 | 33.00 | HsapDv:0000070 | 33rd week post-fertilization stage |
| 231.0 | 238.0 | 33.00 | 34.00 | HsapDv:0000071 | 34th week post-fertilization stage |
| 238.0 | 245.0 | 34.00 | 35.00 | HsapDv:0000072 | 35th week post-fertilization stage |
| 245.0 | 252.0 | 35.00 | 36.00 | HsapDv:0000073 | 36th week post-fertilization stage |
| 252.0 | 259.0 | 36.00 | 37.00 | HsapDv:0000074 | 37th week post-fertilization stage |
| 259.0 | 266.0 | 37.00 | 38.00 | HsapDv:0000075 | 38th week post-fertilization and over stage |

## Grouping terms

Useful when an input spans more than one weekly term.

| id | label | start_dpf | end_dpf |
|---|---|---|---|
| HsapDv:0000045 | prenatal stage | 0 | 266 |
| HsapDv:0000002 | embryonic stage | 0 | 56 |
| HsapDv:0000037 | fetal stage | 56 | 266 |
| HsapDv:0000197 | third LMP month stage | 56 | 77 |
| HsapDv:0000198 | fourth LMP month stage | 77 | 105 |
| HsapDv:0000199 | fifth LMP month stage | 105 | 133 |
| HsapDv:0000200 | sixth LMP month stage | 133 | 168 |
| HsapDv:0000201 | seventh LMP month stage | 168 | 196 |
| HsapDv:0000202 | eighth LMP month stage | 196 | 231 |
| HsapDv:0000203 | ninth LMP month stage | 231 | 266 |

The first weekly term in each LMP month is marked `{notes="debatable"}` on its
`part_of` axiom — the ontology itself flags the month boundary as uncertain. Do
not treat an LMP month assignment as a firm claim about a week at its edge.

Within the embryonic branch the Carnegie stages also group under
`HsapDv:0000205` morula stage, `HsapDv:0000006` blastula stage,
`HsapDv:0000010` gastrula stage, `HsapDv:0000012` neurula stage and
`HsapDv:0000015` organogenesis stage. These carry no dpf annotations and are
morphological groupings.

`HsapDv:0000004` "cleavage stage" also sits here in older mappings but is
**obsolete**, `replaced_by HsapDv:0000005` (Carnegie stage 02). Twenty-one
terms in this release are obsolete — almost all in the postnatal branch, where
the whole `HsapDv:0000080`-`0000094` block (`child stage`, `adult stage`,
`young adult stage`, `adolescent stage`, `aged stage` …) has been retired in
favour of the explicitly-bounded replacements. Those retired labels are exactly
the words that appear in free-text metadata, so a lexical match on a stage
string will land on an obsolete term unless you check. `$OQ term` reports
`deprecated`; read it before emitting any CURIE.
