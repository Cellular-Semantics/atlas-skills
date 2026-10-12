---
name: map-to-ontology
description: Map free-text metadata fields to ontology terms by working out what the text means, proposing what the ontology probably calls it, and testing those proposals with lexical and graph queries. Use when a record carries annotator-written tissue, cell type, stage, species or anatomical strings that need resolving to CURIEs. Not for bulk string matching.
---

# Mapping free text to ontology terms

The tools return evidence, never an answer, a score or a trustworthy ranking.
Every choice is yours and the reason has to end up in your report.

**Mapping to HsapDv? Read [`references/hsapdv.md`](references/hsapdv.md) first.**
Prenatal stage labels are ordinals running one ahead of the age they denote —
"9th week post-fertilization stage" means a fetus of eight weeks — so matching
the number in the input to the number in the label is wrong every time.

## The tool

```
uvx --from "${OQ_FROM:-git+https://github.com/Cellular-Semantics/atlas-skills@pkg-onto-query--v0.3.0#subdirectory=packages/onto-query}" oq <command>
```

Keep the quotes; an unquoted command in a variable does not word-split under
zsh. If `$OQ_BIN` is set, run `"$OQ_BIN" <command>` instead and say so, because
that is a local build rather than the pin. **Needs onto-query ≥ 0.3.0.**

Every command prints `{tool, version, command, backend, params, warnings,
result}`. **Read `warnings` every time** — they carry the things that cost you a
wrong answer. `$OQ <command> --help` gives the exact result shape.

**Ubergraph** holds ~45 OBO ontologies with inference closure, common ancestors
and information content. **OLS4** holds 287 lexically, plus one-hop relations
and hierarchy walks. For an ontology outside Ubergraph (EHDAA2, EHDA, VHOG) you
can search and read relations but not reason — say so in the report.

## Working a batch

You may be given one record or many. Working several in one session is much
cheaper than one at a time, because this file and the release check are read
once rather than once per record — measured at roughly half the cost and half
the turns per record at a batch of five.

**How many records to take at once, and which model to run, are the caller's
choice, not this skill's.** A skill cannot select a model; set it for the
session (`claude --model …`, `/model`, or settings) and send records in groups.
Judgement is what this skill is for, so a cheaper model is a different
experiment rather than a cheaper run of the same one — on 49 records a smaller
model agreed on 38 and named a mean 1.5 rejected rivals against 4.5, naming
none at all on 19 of them. Those 19 fail the exit test below whatever term they
reached. If nobody reviews the output, that matters; if a curator signs it off,
it may not.

**Per session, once only:**

```
$OQ release -o <ontology>
```

Read `agree`: `true`, proceed; `false`, the backends serve different releases,
so name the backend behind every claim; `null`, Ubergraph lacks this ontology.

Then work each record independently and completely before starting the next —
do not batch the lexical probes of different records together, because the
judgement for one record must not be contaminated by another's candidates.
Reuse what you learned about the ontology's naming conventions; do not reuse a
mapping. Emit one report object per record.

## The shape of the work

**Prepare → Find → Prune → Confirm → Judge.**

One rule holds it together: **never pull detail on a candidate you could have
rejected from its name.** Measured on Uberon `skin` — 121 hits, 33.7 kB — the
labels are 4.0 kB and the definitions and synonyms 17.8 kB. Read names, fetch
detail only for survivors.

Two failure modes this exists to replace: picking a term because it came back
first, and mechanically splitting or stemming the input and searching the
fragments. Work out what the text *means*, then what the ontology *calls* it.

Spending heavily on an easy record is as much a failure as getting a hard one
wrong. Most records finish at Find and Prune.

---

## 1 · Prepare

No queries. Most of what settles a hard record is decided here.

### What have you been given?

Latent knowledge is the right tool; write down which of these it is.

- **Key–value fields.** Keys are whatever the submitter chose. Read every key —
  the key types the value, so `bone=frontal` is a bone, not the frontal cortex.
- **One string, no context.** If ambiguous it stays ambiguous. Say so.
- **A string plus free text** — see below.
- **Only a study name.** `bayraktar_2024_heart` gives the organ and nothing
  else. It can supply context, never the answer; say the organ came from there.
- **Nothing usable.** Say so and stop.

### Several fields, different grain

`Region=Telencephalon | Subregion=Cortex | dissection=Occipital cortex`

**Search the most granular; the coarse ones are checkable context**, not rivals
and not extra tokens. Judge grain on the *values* — the most granular field
often has the least tidy key. Beware: a `dissection` field may instead name a
*block* that is coarser than the annotation (`Pons/Cereb`), in which case say
which you mapped and why.

### A value that is not a name

- **Abbreviation** — expand before searching, using a sibling field where there
  is one. `organ=LI` beside `organism part=liver` means liver, not large
  intestine. State any expansion you assumed.
- **Description** — `heart without node`, `full reproductive tract`. Work out
  the structure and name it as an ontology would. Do not search the description.
- **Quantity or code** — does not reach a lexical probe. See below.

### Free text

Not a search string; tokenising it yields noise with a rank attached. Two uses:
**lift a phrase** if the author names the structure outright, or **hold it for
Confirm** and read it against candidate definitions — a definition is also a
paragraph of description, and the two compare in a way neither searches.

### Is it searchable at all? `convert`

A quantity or a code is not. `15`, `20 PCW`, `8+3`, `GSM4116579`, `D12` — no
target label contains them, and a probe on `15` matches unrelated terms and
reports a rank, which reads as signal.

For these: **convert, construct, verify.**

1. **Read the field key** — `age=15` beside `age_units=weeks post conception`
   means something; `15` alone means nothing.
2. **Use the ontology's advice document** for the convention, or read it off
   twenty real labels with `$OQ cohort -o <ont> --label-contains "<pattern>"`.
3. **Construct the term, then verify** with `$OQ term <CURIE> -o <ont>`,
   checking its annotations bracket your value. A lexical hit is not the test.

**No unit and no reference point anywhere in the record → not mappable.** That
is a question for the submitter. Do not pick the commonest convention and hope.

### Write the query string

One string, constructed, often several fields joined as an ontology would word
them:

| record | search |
|---|---|
| `structure=spine`, `region=thoracic` | `thoracic spine` → UBERON:0006073 |
| `bone=frontal`, `site=calvaria` | `frontal bone` |
| `obs_tissue=spinal cord; brachial` | `brachial spinal cord` |
| `tissue=cortex`, `organ=kidney` | `kidney cortex` → UBERON:0001225 |

Probe both readings where two are plausible — `-q` repeats, so it is one call.

**A separator is not an instruction to split.** `brain; stroma` is stroma of
brain. Mapping halves separately gives two wrong answers instead of one.

**Composing is not filtering.** Join fields when they *together name one
structure*; the test is whether a curator would write the phrase on a slide
label. A multi-token query is conjunctive, so adding `human` or `adult` returns
zero.

### Could a plain lexical match get this wrong?

Signals that it could: the string names more than one thing
(`Cornea/Conjunctiva`); it carries a number, unit or abbreviation (`12 pcw`,
`wk 8`, `LI`); it reads as a description rather than a name
(`full reproductive tract`); or it is a **short common ambiguous word** —
`skin`, `muscle`, `brain`, `cortex`.

That last class is the one that bites hardest, because a probe on it often
returns a clean-looking hit. `cortex` returns exactly one exact term on the
label. The record almost certainly means the cerebral, renal or adrenal cortex,
and nothing in the result says which. **Flag the string here**; it is what the
short path below checks against.

### Is this a one-annotation record?

Ask it explicitly, because the answer licenses the short path below. A record
is **one-annotation** when everything it says about the target ontology reduces
to a single name — one field, or several that compose into one name — and
nothing left over discriminates between candidates.

`study_level=dorsal root ganglion` is one-annotation. So is `structure=spine` +
`region=thoracic`, because the two compose. `region=apex` with
`publication_id=…_heart` is **not**: the organ comes from outside the tissue
fields and is doing real work.

Developmental stage does not make a record multi-annotation. It is carried as a
validator, but Uberon's stage axioms are too coarse to separate candidates at
the grain these records use — see the developmental survey for what is and is
not usable. Note it as unchecked and do not spend moves on it.

### Write the context

Tag everything not in the string by the stage that reads it:

- **disambiguates** — used now, while building the string.
- **discriminates** — held for Confirm. **Gross location belongs here** and is
  the most useful thing in the block.
- **validates** — species, stage. Checked at Confirm.
- **unexplained** — goes in the report.

**Sex is the one real constraint**, and latent knowledge usually settles it.

---

## 2 · Find

A menu, not a staircase: **the last failure signal chooses the next move.** Do
not run them all. Report moves by the slug beside each heading.

### `exact`

```
$OQ lexical -q "<string>" -o <ont> --probes exact --compact
```

Whole-string match on label or any synonym. Search **the string Prepare built**.
`found_by.exact.matched_fields` names the channel, which is the trustworthy
part: it tells you the *grain* of what you found. Any hits → **Prune**.

**For a one-annotation record, drop `--compact`.** You are about to decide on
the definition, and compact omits it to save bandwidth you are not spending
here. One full probe beats a compact probe plus a `term` call.

#### The short path

**Stop after this probe — no further move — when all four hold:**

1. Prepare called the record **one-annotation**.
2. The probe returned **exactly one** term.
3. It matched on **label or exact synonym**. Broad, narrow and related do not
   qualify: those scopes mean the term is wider or narrower than your text, and
   that difference is worth a second move.
4. Prepare did **not** flag the string as ambiguous, and the definition the
   probe returned is about the sense the record means.

Then write the why-this-not-that line and finish. `dorsal root ganglion` is the
whole of its record and is the exact label of `UBERON:0000044`; it needs one
probe, and a run that spent three probes and two `term` calls on it settled
nothing the first call had not.

**This is not the count rule that used to live here, and the difference is
condition 4.** The old rule exited on one term and nothing else, which `cortex`
defeats: one hit, matched on the label, and `UBERON:0001851` is defined
"Outermost layer of an organ" — not what any record means by cortex. What stops
it is that Prepare flagged `cortex` as a short common ambiguous word before any
query ran. One hit is still not an exit; one hit on an unflagged string, with a
definition that fits and nothing else in the record to weigh, is.

**Both halves of condition 4 are already in your hands.** The flag came from
reading the record and the definition came back with the probe, so nothing here
needs a second call. Do not spend a `term` call to confirm a short-path match.

If any condition fails, carry on as normal.

### `stemmed`

```
$OQ lexical -q "<string>" -o <ont> --probes exact,stemmed --compact
```

Good recall, untrustworthy order. Hundreds of more-specific terms (`skin` 121,
`muscle` 768) is recall working; that is a Prune problem. `rank` is unreliable
within the band (`skin of body` ranks 46th) — never choose on it.
`--probes definition` gives leads, never sufficient alone.

### `alt-names`

When probes return nothing or the wrong kind of thing. Formal over colloquial;
`system`, `tract`, `region`, `zone`; Latinate; singular; species-neutral.

**Substitute one word at a time**, holding the rest fixed:

| given | also try |
|---|---|
| future X | presumptive X, X primordium, X anlage, X bud, developing X |
| control of X | regulation of X, X regulation |
| X formation | X development, X morphogenesis, X differentiation |
| upper / lower X | fore-/hind-, superior/inferior, cranial/caudal X |
| X layer | X lamina, stratum X, X zone |

**Synonyms will not do this for you.** Uberon has 39 `future X` and 44
`presumptive X` terms and only **9 of each** carry the other spelling, so
`future midbrain` returns nothing while `presumptive midbrain` is real. GO has
**3161** `regulation of X` and **4** with a `control of X` synonym. Work out the
*kind* of thing first — precursor, process and cell layer have different
vocabularies.

```
$OQ lexical -o <ont> --probes exact --compact -q "<n1>" -q "<n2>" -q "<n3>"
```

`full reproductive tract` returns **zero** because no term carries all three
tokens. Informative: drop the weakest token, do not conclude the term is absent.

### `region`

When the string is ambiguous but the record says where in the body it came from.

```
$OQ cohort -o <ont> --text-contains "<word>" --under <REGION-CURIE>
```

Narrows before any name is read: `cortex` matches 150 Uberon labels, 14 inside
the kidney. **Use `--text-contains`, not `--label-contains`** — the record's
string is often not the label. `spine` under UBERON:0001130 gives 10 terms by
label with none of them regional, against 16 by label-or-synonym including the
cervical, thoracic and lumbar regions, all reachable only by synonym.

`--label-contains` is for reading a naming convention, where synonyms are noise.

### `common-ancestors`

When every hit is more specific than the input, or hits each cover only part of
it (`Cornea/Conjunctiva`).

```
$OQ common-ancestors -s <CURIE> -s <CURIE> -t <ont>
```

**The seed set is the judgement the tool cannot make.** *Co-annotation* — seeds
genuinely describe one thing — means the common ancestor **is** the mapping.
*Hit set* — seeds merely share a word — is discovery, giving candidates only.
**Never pass a whole hit set in**: split by sense and run once per sense. All 75
Uberon `muscl*` terms give `anatomical structure`; split, the gut layers give
`muscular coat`. The full 768 times out.

**Read the shape of the IC column, not the top row.** One clear winner (cornea +
conjunctiva → `ocular surface region` 57.29, next 44.61: take it). A band then a
cliff (glycolysis + TCA: four within 56.75–60.34, then −39: that band is your
shortlist). A low ceiling (cornea + femur, nothing above 33.75: they share no
meaningful ancestor, which is an answer). IC compares **within one result set
only**.

**Read `missing_seeds`.** A near-miss outranking every full-coverage row usually
means the partition is wrong — `zone of skin` tops the 82 skin-zone seeds and
misses only `skin of body`, which should not have been in the set.

Traversal covers **part_of as well as subclass**; if everything looks like
`anatomical structure`, check `--predicates` kept part_of. This command takes
only curated predicates, because IC compares only across one fixed traversal.

### `relations`

```
$OQ relations <CURIE> -p part_of -d in -t <ont> --direct
```

`in` points at the term, `out` is what it points at. `-p` takes **any predicate
CURIE** — `RO:0002170` connected to, `RO:0002134` innervates. `$OQ term` lists
what a term carries, with CURIEs ready to pass back.

**`--direct` matters.** Without it you get the closure: `UBERON:0002240
develops_from` gives 1 direct edge and 29 through closure.

### `outside-ubergraph`

```
$OQ neighbours <CURIE> -o <ont> -p <PRED> -t <TARGET>
$OQ hierarchy <CURIE> -o <ont> -d up|down
$OQ crosswalk <xref-CURIE> -t <ont>     $OQ xrefs <CURIE> -o <ont>
```

`neighbours` is the only route to EHDAA2's staging links. `hierarchy` reports
subsumption and hierarchical walks separately — EHDAA2 liver has 0 descendants
by subsumption and 26 with part_of. An xref is a pointer, not equivalence; SKOS
mappings are the stronger claim. `neighbours` incoming comes from an endpoint
that dedupes by source and target and warns when that applies.

---

## 3 · Prune

Read names. No further query — the definition and scoped synonyms are already in
the result.

**One hit is not an exit.** `cortex` returns **exactly one** exact hit,
`UBERON:0001851`, defined "Outermost layer of an organ" — not what a record
means by cortex, which is the cerebral, renal or adrenal one. The count fires,
the hit looks clean, and nothing in the result says you are wrong. What says so
is the string: Prepare flagged it as a short common ambiguous word.

Screen on:

- **Sense** — does it describe what the record means, or another sense?
- **Grouping class or structure?** Worth asking when you are choosing between
  several hits, or weighing a term you reached by climbing the graph — a
  cross-cutting parent can top a result set without being anybody's mapping.
  The tells are a definition with a genus and no real differentia, and a bare
  label sitting under `organ part`, `anatomical structure` or `organ component`.
  **Not a test for a single direct hit**: nothing is being grouped there, and
  the second tell needs a parent the probe did not return.
- **Channel.** A **broad** synonym matching means the term is *narrower* than
  your text; a **narrow** synonym means *broader*. Hits arriving **only** on
  narrow synonyms mean the ontology has no term at your grain — `frontal bone`
  reaches `UBERON:0000209 tetrapod frontal bone` that way.
- **Grain** — all hits far more specific than your string means your string is a
  grouping term; the answer is probably their common ancestor.

Survivors → Confirm. Nothing survives → back to Find, knowing why. **A single
hit that fails the screen is a Find trigger, and the one most easily mistaken
for success.**

No limit on shortlist size. If it feels unmanageable you cannot yet say what
distinguishes its members, which is a Prepare problem.

---

## 4 · Confirm

```
$OQ term <CURIE> <CURIE> <CURIE> -o <ont>
```

**Pass the whole shortlist.** Adjudication is comparison: what separates
candidates is a contrast between them, visible side by side and reconstructed
otherwise. Read the definition against the original string, the logical axioms
(often more decisive), synonym scopes, and `in taxon` / stage links against
whatever you tagged *validates*.

Then spend the **discriminates** tags:

- **Does the candidate sit where the record says?** Location decides
  `cortex of kidney` against `cerebral cortex`.
- **Check against the coarser field — a test that can fail.**
  `$OQ relations <CAND> -p part_of -d out -t <ont>`. If `occipital cortex` does
  not reach the telencephalon, the mapping or the record is wrong; say which.
  **It cannot catch the wrong term from the right region**: `UBERON:0016540
  occipital cortex` and `UBERON:0016530 parietal cortex` differ by a digit and
  both return 34 part_of terms including the telencephalon. **Read labels back
  beside CURIEs** — which one batched `term` call makes easy.
- **Read free text against definitions**, not labels.

### Choosing the grain

Two candidates often differ only in how specific they are, and `term` gives you
what settles it. Each block carries a **`specificity`** score — information
content over `subClassOf` and `part_of`, counted over terms the queried ontology
itself defines — and **`subsumed_by`**, naming which other candidates on your
shortlist it sits under.

**The score decides only when one candidate subsumes another.** Then prefer the
more specific term the record's own words justify, keeping sex, side and region
where the record states them. For `uterus | cervix | vagina`:
`internal female genitalia` (53.1) sits under `internal genitalia` (45.8), so
take the sexed term — the record says which sex.

**Where `subsumed_by` is empty for every candidate the score says nothing**, and
the command warns you. Those candidates are on different branches, and a higher
score means only that the term subsumes fewer things. `thoracic wall` scores
92.8 against `rib` 55.5 because Uberon holds two thoracic walls and seventy-two
ribs; for a record reading `3rd to 6th rib` the rib is still the answer, and no
amount of specificity will say so. The text decides.

A near-tie is informative in itself: `caudate-putamen` 71.9 against
`dorsal striatum` 71.2 means the two sit at the same grain, so what matters is
the argument rather than the choice.

Check `found` on every block: absent ontology, CURIE not in the ontology named,
or genuinely no axioms are three different things and the warnings say which.

A validator contradiction is evidence to report, not a silent gate. Computed
taxon constraints are sometimes wrong — say what it said and what you did.

---

## 5 · Judge

Write one line: **why this term and not its nearest rival.**

- No rival nameable → you have not looked enough. Back to Find.
- Cannot separate two → report both, or make one Find move aimed at what would
  separate them.
- Only a related/broad-synonym hit or a definition-only match → not sufficient.

**Two independent channels agreeing is the strongest evidence available.** `skin`
reaches `skin of body` as a related synonym *and* as the top full-coverage
common ancestor of the 82 skin-zone terms; those routes share no assumptions.

**Unresolved is legitimate** and far better than a confident wrong answer. Two
passes through Find and Prune with nothing new learned means unresolved.

## Report

Per record: the CURIE and label or `unresolved`; the why-this-not-that line;
what you took the input to be and which field you searched (say which field you
judged most granular, what you expanded an abbreviation to, and if the organ
came from a study name); which moves you used and which answered, named exactly
`convert`, `exact`, `stemmed`, `alt-names`, `region`, `common-ancestors`,
`relations`, `outside-ubergraph`; the runners-up rejected, each with a reason;
any validator that flagged rather than rejected; anything unaccounted for; and
any move unavailable because the ontology is not in Ubergraph.

**The rejections are the audit trail.** A mapping without them cannot be
debugged six months later, which is the state this skill exists to escape.
