# Developing structures: using EHDAA2 to generate and filter Uberon candidates

Reference for mapping anatomical annotations on **human embryonic** samples,
where the annotator has written the name of the mature structure and the thing
in the sample is its developmental precursor.

This is a candidate-generation route, and one among several. It is not a way of
assigning a stage, and it is not a replacement for the lexical rungs. Read it
when rung 0 has told you the sample is embryonic and the string names an organ.

Sources, and the releases everything below was read off:

- EHDAA2 (`http://purl.obolibrary.org/obo/ehdaa2.owl`), release **2024-01-11**,
  2743 classes in OLS4 of which **2459** are native EHDAA2 (the rest are
  imported AEO and CARO).
- Uberon, read from Ubergraph's `uberon-base.owl` graph, release **2026-06-19**.

## The problem this addresses

An annotator writing up an embryonic dissection names what they recognise. At
CS13 they write `kidney`, `limb`, `lung`. None of those is wrong as English, and
all three map cleanly to a Uberon term by exact lexical match — to the term for
the *mature* organ, which did not exist in the sample.

Lexical probing cannot detect this, because the failure is not lexical. The
string matched, and it matched a real term. What is missing is the knowledge
that at CS13 the human kidney is a mesonephros, the limb is a bud, and the lung
is two buds off a respiratory primordium. That knowledge is in EHDAA2, which is
the only queryable resource that states it at Carnegie-stage resolution.

## Why EHDAA2 and not Uberon's own stage axioms

Uberon does carry `existence starts during` and `existence ends during or
before`. They resolve to species-neutral life-cycle classes. `UBERON:0002328
notochord`:

```
existence starts during            UBERON:0000068  embryo stage
existence starts during or after   UBERON:0000111  organogenesis stage
existence ends during or before    UBERON:0000066  fully formed stage
```

EHDAA2's notochord says CS11 to CS15.

Both are true. Only one of them can separate two candidates for the same
sample, which is the job here. Uberon's axioms will not tell you that at CS13
the mesonephros is present and the metanephros has only just appeared; EHDAA2's
will.

## Where the numbers live

Two OBO relations, asserted on EHDAA2 classes, pointing at HsapDv Carnegie
terms:

- `existence starts during or after` (`RO:0002496`)
- `existence ends during or before` (`RO:0002497`)

Coverage in this release, counted over the 2459 native classes:

| relation | classes carrying it |
|---|---|
| `existence starts during or after` | 2444 (99.4%) |
| `existence ends during or before` | 1058 (43%) |
| `develops_from` | 1862 (76%) |

### The logic is one-sided, and this is the part to get right

Read the relation names literally.

`X existence_starts_during_or_after CS11` says the start of X's existence is at
or after CS11. It follows that **X does not exist before CS11**. It does not
follow that X exists at CS11.

`X existence_ends_during_or_before CS18` says X's existence ends at or before
CS18, so **X does not exist after CS18**. It does not say X survives to CS18.

Together the two give a window that *contains* the true existence interval and
may be wider than it. So:

- **You can refute.** A sample at CS09 annotated `mesonephros` is wrong, because
  mesonephros cannot start before CS11. That is a sound inference and it is the
  useful one.
- **You cannot confirm.** A CS13 sample annotated `metanephros` is *not
  excluded* by metanephros starting at CS13. It is not thereby confirmed.

Use the brackets to drop candidates, never to select one. A candidate that
survives the bracket has not been endorsed by it.

### An absent end bound is silence, not persistence

57% of classes have no `existence_ends_during_or_before`. That is an absent
upper bound, which is what you would expect for a structure that persists into
the fetus — but it is equally what an unasserted axiom looks like. Do not
report "exists from CS12 onwards" when what the ontology said was "does not
exist before CS12, and says nothing about an end". And see the next section:
through OLS4 an absent end bound may not even be absent upstream.

### OLS4 silently drops the end bound when it equals the start

**This is the most dangerous thing in this file.** 224 EHDAA2 classes exist at
exactly one Carnegie stage, with `existence_starts_during_or_after` and
`existence_ends_during_or_before` both pointing at the same HsapDv term.
OLS4's term-graph endpoint deduplicates edges by source and target, keeps one
predicate, and discards the other.

`EHDAA2:0001570 pronephros` asserts start CS09 **and end CS09** in the released
OWL. What `$OQ neighbours` returns is:

```
existence starts during or after   HsapDv:0000016  CS09
part of                            EHDAA2:0001601  urinary system
```

The end bound is gone. Not flagged, not empty — absent.

Measured on this release: of the 1058 classes with an end bound, the 834 whose
end differs from their start are reported correctly (10 of 10 sampled), and all
224 whose end equals their start lose it (14 of 14 sampled).

The damage is that it fails in the worst direction. These are the single-stage
transient structures, the most tightly bounded terms in the ontology and the
ones that refute most. Through OLS4 they look open-ended, so a sample twenty
stages too late passes a bracket that should have excluded it immediately.

**So an absent end bound has three possible meanings, not two**: no end
asserted, an end that equals the start, or an end lost in transport. You cannot
tell which from `neighbours` output.

Until this is fixed, treat a term reported with a start bound and no end bound
as **unbounded above but unverified**, and where the decision turns on it, check
the released OWL. The data is not lost upstream — OLS4's own v2 class endpoint
keeps both restrictions in its `relatedTo` array:

```
prop= BFO_0000050  value= EHDAA2_0001601
prop= RO_0002496   value= HsapDv_0000016
prop= RO_0002497   value= HsapDv_0000016
```

so the fix is for `neighbours` to read `relatedTo` rather than the v1 graph
endpoint. Until then this is a known hole in the method, and a mapping that
depended on an absent end bound should say so.

### The ceiling is CS20, not CS23

Every stage target in this release falls between `HsapDv:0000003` (CS01) and
`HsapDv:0000027` (**CS20**). Nothing points at CS21, CS22 or CS23.

CS20 is 51-53 dpf, roughly 7.3 weeks post fertilization. So this whole route is
silent on the last fortnight of the embryonic period and on everything fetal.
For a sample past about 7.5 pcw, EHDAA2 has no bracket to offer and you should
say so rather than reading the absence as a negative result.

**57 classes are anchored to Carnegie substages instead** —
`HsapDv:0000031`-`0000035`, that is CS05a/b/c and CS06a/b — of which 39 carry a
Uberon xref. Those substage terms have no dpf annotations of their own (see
`hsapdv.md`), so they cannot be reached from an age, and they sit at CS05-CS06
where nothing in a dissection corpus lands anyway.

They matter because of *where* they concentrate: the extraembryonic and early
conceptus branch. Ten of them are yolk sac terms, nine chorion, eight
trophoblast, three amnion. So for an annotation of `yolk sac` — the fourth
commonest tissue string in the HDCA corpus, 72 rows — the bracket is technically
present and practically useless. `EHDAA2:0002212 secondary yolk sac` xrefs
`UBERON:0001040 yolk sac` and starts at CS05c with no end, which excludes
nothing at any stage a sample is likely to carry. Report that the route had
nothing to say, rather than that the annotation passed a check.

## The xref bridge, and the judgment it needs

Uberon and EHDAA2 are linked by `hasDbXref` on the Uberon side. In this release
**1450 Uberon classes carry 1458 distinct EHDAA2 ids**, and only two EHDAA2 ids
map to more than one Uberon class. So the crosswalk is effectively one-to-one
and round-trips in both directions:

```
$OQ crosswalk EHDAA2:0001137 -t uberon      # -> UBERON:0000081 metanephros
$OQ xrefs UBERON:0002102 -o uberon          # -> ... EHDAA2:0002133 ...
```

**An xref is an annotation, not an assertion of equivalence**, and here the gap
is not pedantic. The two ontologies were built to different purposes and their
terms are not always the same grain. `EHDAA2:0001042 lung system` xrefs
`UBERON:0002048 lung`; those are not the same thing, and which one your
annotation means depends on what was dissected.

So the crosswalk gives you a lead to adjudicate, and the adjudication is yours:

- **Read both definitions before accepting the pair.** EHDAA2 labels are often
  terser than Uberon's and the difference hides in the definition.
- **Check the grain against what the sample actually is.** A system term and an
  organ term are both defensible mappings of `lung`; they are not
  interchangeable in a dataset.
- **Say in the report that you went via EHDAA2**, and name the EHDAA2 term you
  bridged through. Otherwise the Uberon CURIE looks like a direct lexical hit
  and nobody can later see where it came from.

### Retired EHDAA2 classes hide behind a prefix

EHDAA2 has retired classes, and Uberon records their xrefs under a different
prefix: **`RETIRED_EHDAA2:`**. 131 Uberon classes carry 130 such ids.

```
$OQ crosswalk EHDAA2:0003198 -t uberon          # -> []          <- silent miss
$OQ crosswalk RETIRED_EHDAA2:0003198 -t uberon  # -> UBERON:0005417 forelimb bud
```

The first returns an empty list, not an error. If a crosswalk comes back empty
and you expected a hit, retry with the `RETIRED_` prefix before concluding the
term is unmapped.

This matters more than the counts suggest, because what got retired was often
exactly the developmental-precursor class you are looking for. EHDAA2 no longer
has a limb bud term — it was retired, and the bud survives only as
`upper limb bud ectoderm` and `upper limb bud mesenchyme`, both *parts of*
`EHDAA2:0002133 upper limb`. EHDAA2 itself uses the mature name for the bud
stage. Uberon keeps the distinction, and the only link to it is the retired
xref.

## Two develops_from chains, and what each is for

Both ontologies assert `develops_from`, and they are not redundant.

`UBERON:0000081 metanephros` develops from metanephric mesenchyme, metanephric
ureteric bud and caudal part of the nephrogenic cord — a tissue-lineage account.
`EHDAA2:0001137 metanephros` asserts no `develops_from` at all; its *parts* do,
with `metanephros drainage component` developing from the ureteric bud.

Read the Uberon chain when you want to know what a structure is made from. Read
the EHDAA2 chain when you want the named structure that occupied the same place
at an earlier stage, which is usually the question a mis-stated annotation
raises.

### Name the precursor before you walk to it

Before any graph move, try the lexical one the skill's rung 2 describes:
substitute one word and search again. Uberon names developmental precursors
seven different ways, and which one it used for your structure is not
predictable:

| pattern | Uberon terms |
|---|---|
| `X primordium` | 79 |
| `X bud` | 63 |
| `presumptive X` | 44 |
| `future X` | 39 |
| `X anlage` | 12 |
| `developing X` | 8 |
| `X rudiment` | 2 |

247 terms for one idea. **The ontology's synonyms will not bridge these for
you**: only 9 of the 39 `future X` terms carry a `presumptive X` exact synonym
and only 9 of the 44 the reverse. `future spinal cord` does carry
`presumptive spinal cord`; `presumptive midbrain` carries only
`presumptive mesencephalon`, so a search for `future midbrain` returns nothing
at all while the term sits there under the other spelling.

So for an annotation of `midbrain` on a CS10 sample, run the substitutions
before reaching for `develops_from`. It is one lexical call against seven
spellings, and it often lands directly on the term a graph walk would have
taken several hops and a crosswalk to reach.

### Reason over the chain in Ubergraph, not in EHDAA2

EHDAA2's `develops_from` is sparse exactly where you need it. None of the three
terms that a real corpus refuted — `mesencephalon`, `medulla oblongata`,
`spinal cord` — carries a `develops_from` in either direction in EHDAA2. The
chain that gets you to the stage-appropriate term is Uberon's, and it is in
Ubergraph with full closure over the property hierarchy and chains.

So the shape of the move is: **refute in EHDAA2, navigate in Uberon, re-check
the bracket in EHDAA2.** Cross back and forth rather than trying to do it all
on one side.

**Which edge carries the answer varies, so try a set.** Three worked cases,
three different edges:

| annotation | refuted because | edge that found it | answer |
|---|---|---|---|
| `Mesencephalon` at CS18 | `EHDAA2:0000615` is CS09-CS11 | `develops_from`, direction `in` | `UBERON:0001891` midbrain |
| `spinal cord` at CS12 | `EHDAA2:0001255` starts CS13 | `develops_from`, direction `out` | `UBERON:0006241` future spinal cord |
| `medulla oblongata` at CS17 | `EHDAA2:0001088` starts CS18 | `part_of`, direction `out` | `UBERON:0005290` myelencephalon |

The third is the one that breaks a single-edge recipe. `UBERON:0001896 medulla
oblongata` has **no** `develops_from` in Uberon at all — `relations ... -p
develops_from -d out` returns zero. What carries the developmental relation is
`part of myelencephalon`, because the embryonic vesicle is modelled as the
whole rather than as the precursor. A walk that only follows `develops_from`
finds nothing and reports the annotation unmappable.

**Direction follows from which way the bracket failed.** If the observed stage
is *later* than the term's end bound, the annotation names a structure that has
been superseded, and you want what develops *from* it — direction `in`. If the
observed stage is *earlier* than the start bound, the structure has not formed
yet and you want its precursor — direction `out`.

```
$OQ relations <UBERON CURIE> -p develops_from -d in  -t uberon   # too late
$OQ relations <UBERON CURIE> -p develops_from -d out -t uberon   # too early
$OQ relations <UBERON CURIE> -p part_of       -d out -t uberon   # neither worked
```

**Ask for the direct edge first, then the closure.** `$OQ relations` answers
from Ubergraph's `redundant` graph, which is the full transitive closure, and
that is why `spinal cord` going `out` returns 29 terms — `anatomical structure`,
`blastula`, `embryo`, `germ layer` and the rest of the upper ontology, pulled in
because the closure includes the subsumption ancestors of the `develops_from`
targets.

The direct edges live in the `nonredundant` graph, and for the same query there
is exactly **one**:

```
nonredundant   UBERON:0002240 develops_from  ->  posterior neural tube
redundant      UBERON:0002240 develops_from  ->  29 terms
ontology       UBERON:0002240 develops_from  ->  0 terms
```

The `ontology` graph returns nothing because the assertions are OWL
restrictions rather than plain triples; `nonredundant` is the one that means
"direct". The same information is available for an OLS4-only ontology from
`neighbours`, which is asserted and one hop by construction.

So the order is: **direct first, closure second, judgement over the gap.** Start
with the one or two direct parents. If one of them crosswalks into EHDAA2 with
a window that contains your stage, you are done and you never pay for the
closure. Only when the direct edge leads somewhere unusable — `posterior neural
tube` has no EHDAA2 xref at all, so it carries no bracket — escalate to the
closure and work through it.

`$OQ relations` has no flag for this yet; it always answers from `redundant`.
Until it grows one, read the first hop from `$OQ term`, whose `develops from`
list is the asserted one, and treat `relations` as the escalation.

**When you do reach the closure, the bracket is what makes it usable.** Do not
try to filter the 29 by eye, and do not pick on plausibility of the label
alone — read the definition of anything you are about to accept, because
`future spinal cord` and `posterior neural tube` are both plausible from their
names and only one of them is dated. Crosswalk each candidate back to EHDAA2
and keep the ones whose window contains the observed stage. For `spinal cord`
at CS12 that leaves
`UBERON:0006241 future spinal cord`, whose EHDAA2 counterpart
`EHDAA2:0000674 future spinal cord` is **CS10-CS12** — a window that closes
exactly where the annotation sits. One survivor out of twenty-nine, selected by
the bracket rather than by judgement.

That round trip is the whole method in one move: EHDAA2 refutes, Ubergraph
proposes, EHDAA2 confirms the proposal is in range.

### Walking the EHDAA2 chain is a client-side job

Where you do want EHDAA2's own chain — usually to read the brackets on a run of
precursors in one go — it has to be walked by hand. EHDAA2 is not in Ubergraph,
so there is no inference closure over it, and OLS4 will not give you transitive
ancestors over an arbitrary relation —
`hierarchicalAncestors` follows a per-ontology configured property set
(subClassOf plus part_of) and silently ignores any attempt to override it. The
chain has to be walked one hop at a time with `neighbours`.

That is affordable because the chains are narrow. Of the 1862 classes with a
`develops_from`, 1646 have exactly one parent and the maximum is five:

| walk depth | terms reached, median | worst case |
|---|---|---|
| 1 | 1 | 4 |
| 2 | 2 | 10 |
| 3 | 3 | 16 |

**Stay shallow.** The chains are deep — a median of eight or nine hops to the
root, maximum sixteen — and they terminate in germ layers:

```
ascending aorta -> outflow tract ascending aorta -> outflow tract endocardium
  -> conus cordis -> primitive heart tube endocardium -> endocardiogenic tissue
  -> cardiogenic splanchnopleure -> splanchnopleure -> lateral plate mesoderm
  -> mesoderm -> epiblast -> inner cell mass
```

By hop three you are at `lateral plate mesoderm`, which is not a candidate
mapping for a tissue annotation. One or two hops is candidate generation;
beyond that is germ-layer trivia. If a walk needs to go deeper to find anything
plausible, the answer is that EHDAA2 has nothing for this annotation.

## Working with the backends

EHDAA2 is **OLS4-only**. Everything Ubergraph does — `common-ancestors`,
`relations`, `term`, `cohort`, information content, closure — is unavailable
for it. What works:

```
$OQ lexical -q "<string>" -o ehdaa2 --probes exact,stemmed
$OQ neighbours <EHDAA2 CURIE> -o ehdaa2
$OQ hierarchy <EHDAA2 CURIE> -o ehdaa2 -d up|down
$OQ crosswalk <EHDAA2 CURIE> -t uberon
```

`neighbours` is the one that matters: it returns every asserted one-hop
relation in both directions with labels resolved, and both existence relations
are in there.

Four traps in that list.

**`$OQ term` on an EHDAA2 CURIE returns an empty result, not an error.** You
get `{"annotations": {}, "relations": {}}`, which reads as a term with no
axioms rather than as a backend that does not hold this ontology. If a term
looks bare, check you are not asking Ubergraph for something only OLS4 has.

**`$OQ cohort -o ehdaa2` errors with "ehdaa2 is not in Ubergraph".** So the
usual move for reading a naming convention off real labels is unavailable here.
Use repeated `lexical --probes stemmed` instead, and expect to work harder.

**`neighbours` loses an end bound when it equals the start bound.** 224
classes are affected and they are the ones that refute best. See the section
above; this is the failure mode most likely to produce a confident wrong answer.

**EHDAA2 declares no preferred prefix, so OLS4 cannot scope results to it.**
Every lexical call warns about this, and the warning is real:

```
$OQ lexical -q "limb" -o ehdaa2 --probes exact   # -> AEO:0000172  limb
```

That hit is an imported AEO class, not an EHDAA2 term. **Check the prefix on
every hit** before using it; roughly a tenth of what OLS4 returns for `-o
ehdaa2` is AEO or CARO.

### Check the releases

```
$OQ release -o ehdaa2 --expect 2024-01-11
$OQ release -o uberon
```

For EHDAA2, `release` reports OLS4 only and Ubergraph `null` — that is the
"outside Ubergraph" case, not a version problem. If the version has moved off
2024-01-11, the prose here still describes how EHDAA2 encodes time, but
re-derive any specific bracket and say in your report that the reference was
stale.

For Uberon the two backends reload independently and `agree: false` is common —
it was false when this file was written (OLS4 2026-10-01 against Ubergraph
2026-06-19). Name the backend behind any claim you make while they disagree.

## Recipe

Enter here only when rung 0 has established that the sample is **embryonic and
at or before roughly CS20**, and that the annotation names an organ or region
rather than a quantity.

1. **Get the stage first, as a Carnegie stage.** The bracket is only usable
   against a Carnegie stage; see `hsapdv.md` for converting an age, and for the
   rule that an explicit Carnegie stage beats a derived age. Without a stage
   this route has nothing to filter on and you should map lexically instead.

2. **Map the string lexically against Uberon**, as rungs 1 and 2 would have you
   do anyway. This gives the mature-organ term the annotator probably meant.

3. **Cross into EHDAA2.**
   ```
   $OQ xrefs <UBERON CURIE> -o uberon        # look for an EHDAA2: value
   ```
   If there is no EHDAA2 xref, that is informative rather than a dead end — go
   to step 6.

4. **Read the bracket.**
   ```
   $OQ neighbours <EHDAA2 CURIE> -o ehdaa2
   ```
   Take `existence starts during or after` and `existence ends during or
   before`. Test the sample's stage against the window, remembering that it can
   only refute.

5. **If the bracket excludes the stage, navigate in Uberon, not in EHDAA2.**
   EHDAA2's `develops_from` is sparse and is often absent on exactly the term
   that was refuted. Go back to the Uberon term and walk one hop in Ubergraph,
   choosing direction from how the bracket failed: `-d in` when the stage is
   later than the end bound, `-d out` when it is earlier than the start bound.
   Try `develops_from` first and `part_of` when that returns nothing — the
   embryonic vesicle is sometimes modelled as the whole rather than as the
   precursor. Then crosswalk every candidate back into EHDAA2 and keep only
   those whose window contains the observed stage. The bracket is the filter;
   going `-d out` returns enough upper-ontology noise that nothing else will
   do.

6. **If the mature name has no EHDAA2 term at all**, the structure does not
   exist under that name in the embryo. Search EHDAA2 for what the region is
   called at this stage — `lexical --probes stemmed` on a word from the
   annotation, or `hierarchy -d down` from the system term it would belong to —
   and crosswalk the candidates back to Uberon.

7. **Adjudicate the grain** of every crosswalked pair, and apply the skill's
   ordinary exit test: name the rival and say why not it. The bracket is
   evidence for the report, not a substitute for that line.

8. **If nothing in range can be found, fall back to the mature term.** Emit the
   term the lexical rungs gave you, with the refutation recorded beside it. A
   region annotation is worth keeping; the claim that the structure had formed
   is what you are withdrawing. Do not keep walking for a better fit.

9. **Report the route.** The CURIE, the EHDAA2 term you bridged through, the
   bracket, whether the bracket refuted or merely failed to refute, and whether
   the term you are emitting is the stage-appropriate one or the mature
   fallback.

## Worked examples

> These are drawn from well-known developmental anatomy rather than from
> annotation data, and they were checked against the two releases named at the
> top. They show the mechanism. **HDCA cases are still to be added**, and until
> they are, nothing here has been tested against real annotator strings.

### `limb`, sample at CS13

Lexical on Uberon gives `UBERON:0002102 forelimb` for `upper limb`, which is an
exact synonym — so the naming shift from "upper limb" to "forelimb" is Uberon's
own, and happens before EHDAA2 is involved at all.

`UBERON:0002102` xrefs `EHDAA2:0002133 upper limb`, which exists from CS12. CS13
is not excluded, so the bracket does not refute. But EHDAA2's `upper limb` has
`upper limb bud ectoderm` and `upper limb bud mesenchyme` as parts, both CS12 to
CS14, which says plainly that at CS13 this thing is a bud.

The bud term is in Uberon as `UBERON:0005417 forelimb bud`, reachable only
through `RETIRED_EHDAA2:0003198` because EHDAA2 retired its own bud class.

The point of the example: the bracket on `upper limb` did not refute anything,
and the useful signal came from its parts. A bracket that fails to refute is
not an endorsement.

### `kidney`, sample at CS18

EHDAA2 has no `kidney` term, and `UBERON:0002113 kidney` carries no EHDAA2 xref
at all. Step 3 comes back empty, which sends you to step 6.

Searching EHDAA2 for the urinary system gives three terms where Uberon's lexical
match gave one:

| EHDAA2 | exists | Uberon |
|---|---|---|
| `EHDAA2:0001570` pronephros | CS09 only | `UBERON:0002120` |
| `EHDAA2:0001130` mesonephros | CS11 - CS18 | `UBERON:0000080` |
| `EHDAA2:0001137` metanephros | CS13 - (no end asserted) | `UBERON:0000081` |

The bracket refutes the pronephros outright and leaves two. `kidney` at CS18 is
genuinely ambiguous between a mesonephros at the very last stage of its
existence and a metanephros, and the mapping should say so and ask rather than
pick. At CS12 the same bracket would have left only the mesonephros.

This example also carries the warning from the backend section. The pronephros
row reads `CS09 only` because that is what the released OWL says. Through
`$OQ neighbours` it reads `CS09 -` with no end, and the refutation that makes
this example work does not happen. The row above was read off the OWL, not off
the tool.

### `lung`, sample at CS11

`EHDAA2:0004089 lung bud` exists CS11 to CS12, xrefs `UBERON:0000118 lung bud`.
`EHDAA2:0000943 left lung` and `EHDAA2:0001730 right lung` do not start until
CS13, so a CS11 sample annotated `left lung` **is refuted** — the first case in
these examples where the bracket does real work.

### `pancreas`, sample at CS17

`EHDAA2:0001367 pancreas` starts at CS17, so the annotation is not excluded. But
`dorsal pancreas` and `ventral pancreas` both exist CS17 to CS18 — a hard end
bound, because they fuse — and at CS17 a dissected "pancreas" is one or both of
those. Uberon has `UBERON:0009708` and `UBERON:0009709` for them.

Two structures with a stated end bound inside the window of their parent is a
reliable signal that the parent term is too coarse for the stage.

## What a real corpus does to this

Run against 361 distinct (stage, tissue) pairs from HDCA, the route's behaviour
is lopsided in a way worth knowing before you rely on it.

**Only 33 of 205 distinct strings match an EHDAA2 label exactly.** For the other
84% the work is step 6 — searching EHDAA2's vocabulary — not step 3's crosswalk.
Budget accordingly.

**The bracket refutes rarely, and when it does it is usually right.** Across the
tested pairs it refuted on three brain terms, the vertebral series and the
calvaria, and passed everything else. A route that refuted often would be
suspect; this one mostly returns "not excluded", which is the honest answer and
is not a mapping.

**Where it earns its keep is discriminating within a series.** The HDCA skeletal
study carries `upper vertebrae`, `mid vertebrae`, `mid-low vertebrae` and
`lower vertebrae` at CS16. EHDAA2 has `atlas pre-cartilage condensation` and
`axis pre-cartilage condensation` at CS15-CS16, but the cervical cartilage
condensations do not start until CS17 and the thoracic ones until CS18. So at
CS16 `upper vertebrae` has a candidate and `mid vertebrae` does not — the same
string family, split by the bracket, which no lexical probe could do.

The limb pair behaves the same way in the opposite direction. `upper limb bud
ectoderm` and `upper limb bud mesenchyme` run CS12-CS14, so `forelimb` at CS13
is a bud and `forelimb` at CS16 is not. Both are in the corpus.

**When the refutation cannot be repaired, fall back to the mature term and say
so.** `calvaria` at CS16 is refuted — `parietal bone primordium` and
`interparietal bone primordium` both start at CS19 — and EHDAA2 offers nothing
at CS16 to put in its place. `mid vertebrae` at CS16 fails the same way, with
the sclerotome terms that look like the obvious fallback having ended at
CS13-CS15.

Return the mature structure anyway: `UBERON:0004339 vault of skull`,
`UBERON:0002347 thoracic vertebra`. This is the general rule and it holds
wherever the route runs out:

> **If no stage-appropriate earlier term can be found, use the mature structure
> term, and record the refutation beside it.**

The reasoning is that the annotation is not meaningless — a curator dissected
something and called it the calvaria, and that names a real region of the
specimen. What is wrong is the implication that the named structure had formed.
Returning nothing throws away a usable region annotation to avoid overstating a
developmental claim, which trades a large loss for a small one. The mature term
with the refutation attached loses neither.

Two conditions on using it. The refutation has to be **in the report**, not just
in your reasoning, or the fallback silently becomes the same wrong answer the
route exists to catch. And do not keep walking the chain looking for something
that fits — a term three hops away with a window that happens to span the stage
is not evidence about what was dissected, and the fallback is honest in a way
that is not.

### Label identity across the bridge is not term identity

`UBERON:0001900 ventral thalamus` xrefs `EHDAA2:0004470 **subthalamus**`. EHDAA2
also has `EHDAA2:0004471 ventral thalamus`, and that one has **no Uberon xref at
all**. Uberon lists "subthalamus" as an exact synonym of ventral thalamus, so the
xref is defensible — but it means crosswalking from the EHDAA2 term whose label
matches your string returns nothing, while the Uberon term whose label matches
lands on a differently-labelled EHDAA2 term.

Check the label on both ends of a crosswalk. Matching labels are not evidence
the bridge went where you think, and mismatched ones are not evidence it went
wrong.

### EHDAA2's "future X" collapses to Uberon's "X"

`EHDAA2:0000234 future cerebral cortex` (CS16-) xrefs `UBERON:0000956 cerebral
cortex`. `EHDAA2:0000596 future corpus striatum` (CS16-) xrefs
`UBERON:0000369 corpus striatum`. Uberon has no "future cerebral cortex" or
"future corpus striatum" to receive them.

This is the reverse of the `presumptive midbrain` case, where Uberon *did* keep
the distinction, and you cannot tell which you are in without looking. When the
EHDAA2 label says "future" and the Uberon label does not, say so in the report:
the CURIE you emit is for the mature structure and the ontology that knows about
the stage called it a precursor.

## Other things that will bite

- **A bracket is per-term, not per-sample.** Several terms from one record can
  each survive their bracket and still be mutually inconsistent. The bracket
  does not check coherence across a record.
- **`part_of` in EHDAA2 is stage-bearing in a way Uberon's is not.** A part can
  have a narrower existence window than its whole, as the limb bud tissues do
  inside `upper limb`. Reading only the whole loses the signal.
- **`hierarchy` on EHDAA2 needs the hierarchical flavour.** Subsumption alone
  reports that the liver has no parts: `EHDAA2:0000997` has 0 descendants by
  subClassOf and 26 once part_of is followed. The command reports both; read
  the right one.
- **EHDAA2 labels carry no synonyms configured in OLS4**, so lexical recall is
  worse than it is for Uberon. A miss is weak evidence that a term is absent.
- **The OLS4 end-bound loss hits real annotations, not just principle.** 39 of
  the affected 224 are the per-somite terms `somite 01`-`somite NN`, each
  existing at exactly one stage. Through OLS4 `somite 01` reads CS09 with no
  end; in the OWL it is CS09-CS09. A `somite` annotation at CS16 is refuted by
  seven stages and passes anyway.
- **One label typo in this release.** `EHDAA2:0003471` is
  "upper limb bud mesenchy**e**me". Lexical matching on the correct spelling
  misses it.
- **Do not report an EHDAA2 CURIE as the mapping.** EHDAA2 is the route, not
  the target. The deliverable is a Uberon term, with the EHDAA2 term named as
  evidence.
