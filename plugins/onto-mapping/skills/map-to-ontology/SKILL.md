---
name: map-to-ontology
description: Map free-text metadata fields to ontology terms by working out what the text means, proposing what the ontology probably calls it, and testing those proposals with lexical and graph queries. Use when a record carries annotator-written tissue, cell type, stage, species or anatomical strings that need resolving to CURIEs. Not for bulk string matching.
---

# Mapping free text to ontology terms

You are mapping one or more free-text metadata fields to terms in a target
ontology. The tools return evidence. None of them returns an answer, a score or
a ranking you should trust — every choice is yours, and the reason for it has to
end up in your report.

**If you are mapping to HsapDv, read
[`references/hsapdv.md`](references/hsapdv.md) first.** Its prenatal stage
labels are ordinals that run one ahead of the age they denote — "9th week
post-fertilization stage" means a fetus of eight weeks — so matching the number
in the input against the number in the label gives the wrong term every time.
That file records the release it was written against; check it with
`$OQ release -o hsapdv --expect <version>`.

Week-to-stage conversion defaults to the UK clinical convention (`N weeks` = N
*completed* weeks), names the adjacent term, and states the assumption. **If
the caller states which interpretation they want, use theirs** and say which
you applied.

Two things to avoid, because they are the failure modes this exists to replace:

- Picking a term because it came back first. No relevance score is returned to
  you. Rank, where it is reported, is a loose signal only (see rung 1).
- Mechanically transforming the input string — stripping, splitting, stemming —
  and searching the fragments. Work out what the text *means*, then work out
  what the ontology probably *calls* that.

## The tool

Every invocation looks like this. Keep the quotes — an unquoted command in a
variable does not word-split under zsh, which is the default shell on macOS:

```
uvx --from "${OQ_FROM:-git+https://github.com/Cellular-Semantics/atlas-skills@pkg-onto-query--v0.2.0#subdirectory=packages/onto-query}" oq <command>
```

That default is the pinned release and is what you should normally run. If
`$OQ_BIN` is set in the environment, run `"$OQ_BIN" <command>` instead — a
project developing `onto-query` points it at a local build. In that case
`oq --version` reports something other than the pinned version, and any
behaviour you record is that build's rather than the release's, so say which
you ran.

Every command prints one JSON object:
`{tool, version, command, backend, params, warnings, result}`.

**Read `warnings` every time.** They carry things that will otherwise cost you a
wrong answer: that an ontology isn't in Ubergraph, that local scoping was
unavailable, that a high-scoring candidate misses one of your seeds, that part_of
was dropped from a traversal.

Run `$OQ <command> --help` when you need the exact result shape; each one
documents its output and how to read it.

## Which backend can do what

Check this before planning, with `$OQ ontologies`.

- **Ubergraph holds ~45 OBO ontologies** (Uberon, CL, GO, PATO, MONDO, HsapDv,
  EMAPA, MA, ZFA, FBbt, NCBITaxon and more). For these you get inference
  closure, common ancestors and information content.
- **OLS4 holds 287**, lexically, plus one-hop asserted relations and
  subsumption/hierarchy walks.
- For a target ontology **outside** Ubergraph (EHDAA2, EHDA, VHOG, AAO …) you
  can search and read relations but not reason. Either work with that, or
  `$OQ crosswalk` into a resident ontology, reason there, and say in your report
  that you did.

## Check the release first

Once per ontology per session, before any of the rungs:

```
$OQ release -o <ontology>
```

The two backends reload on unrelated schedules and nothing in an ordinary
response says which release answered it, so an answer assembled from both can
quietly be assembled from two different ontologies. Read `agree`:

- **`true`** — proceed, and you need not check again today.
- **`false`** — the backends serve different releases. Finish the mapping if
  you can, but name the backend behind every claim in your report, and treat
  any disagreement between them as the version gap until shown otherwise.
- **`null`** — one backend does not have this ontology at all. For Ubergraph
  that is the "outside Ubergraph" case above, not a version problem.

The result is cached by date, so a second call on the same day costs nothing
and returns `from_cache: true`. If a `previous` block says the release moved
since the last check, re-derive anything you had written down about this
ontology rather than trusting it.

Pass `--expect <version>` when a reference file records the release it was
written against — see the HsapDv note for a worked case.

## Work the ladder

Cheapest rung first. Leave a rung when you hit one of its named failure signals.
Most records finish at rung 1 or 2, and spending heavily on an easy record is as
much a failure as getting a hard one wrong.

**Rung 0 chooses where you enter.** It is not a warm-up for rung 1. Some inputs
carry no searchable text at all, and for those the lexical rungs are not a
cheap first try — they are a waste that produces false leads. Rung 0 says which
of those you have.

### Rung 0 — triage

Read the whole record, all fields together, and write down three things.

**Could a plain lexical match get this wrong?** Signals that it could: more than
one field; the string names more than one thing (`Cornea/Conjunctiva`); it
carries a number, unit or abbreviation (`12 pcw`, `wk 8`); it is a short common
ambiguous word (`skin`, `muscle`, `brain`); it reads as a description rather
than a name (`full reproductive tract`).

**Is the string searchable at all?** Ask it concretely: could a curator find
this term by typing this string into a search box? If the answer is no, no
lexical probe will help: **skip rungs 1 and 2 and enter at rung 3**, whose
tools — `cohort` and `term` — are the ones that work on a quantity.

The answer is no whenever the value is a quantity or a code rather than a name:

| value | why searching fails |
|---|---|
| `15`, `84`, `12.2` | the target term's label contains no digit from this |
| `20 PCW`, `8+3`, `6wk`, `47 day` | the quantity is the content; `PCW` is not in any label |
| `GSM4116579`, `D12`, `S3` | an identifier, not a description |

Searching these is worse than useless. A lexical probe on `15` can match an
unrelated term whose label or definition happens to contain 15, and a rank is
reported for it, which reads as signal when it is noise.

For these the route is **convert, construct, verify** — not search:

1. **Read the field key, because the value does not carry the information.**
   `15` means nothing. `age=15` beside `age_units=weeks post conception` means
   something specific, and `development_stage=15` beside
   `gestational_age_units=weeks` means something two terms away from it. The
   key and its sibling unit fields tell you the quantity and the reference
   point; the number alone tells you neither.
2. **Use the target ontology's advice document** for the conversion and the
   naming convention — `references/hsapdv.md` for developmental stage. Where no
   advice document covers it yet, read the convention off the ontology with a
   rung-3 cohort survey:
   `$OQ cohort -o <ontology> --label-contains "<pattern>"`.
3. **Construct the term you believe is right, then verify it** with
   `$OQ term <CURIE> -o <ontology>`, checking that its own annotations bracket
   your value. That is the exit test for this route; a lexical hit is not.

**If no field in the record supplies the unit or the reference point, the value
is not mappable.** `15` with nothing to say whether that is weeks, months,
years, post-conception or post-menstrual is a question for the submitter, not a
mapping. Say so and stop — do not pick the most common convention and hope.

A mixed string (`6months old human thymus`) is a quantity wrapped in words.
Extract the quantity and take this route; do not search the whole string.

**What is each field for?** Give every field exactly one role and say which:

- **Search term** — joins the lexical query.
- **Structural constraint** — narrows candidates through the graph, not through
  text. A region constrains which cell types are plausible.
- **Validator** — never enters the search; only checks the answer at the end.
  Species and developmental stage are usually validators.

Putting a validator into the search is a common way to get nothing back.
Leaving a search term out throws away signal.

### Rung 1 — exact, then stemmed

Only if rung 0 found searchable text. A quantity or an identifier does not
reach this rung at all.

```
$OQ lexical -q "<string>" -o <ontology> --probes exact
```

Whole-string match against the label or any synonym, case-insensitive. Each hit
reports **which field matched**, in `found_by.exact.matched_fields`:

```
UBERON:0000014  zone of skin    exact_synonym
UBERON:0002097  skin of body    related_synonym
UBERON:0001003  skin epidermis  broad_synonym
UBERON:0002199  integument      related_synonym
```

A **broad** synonym matching your text means the term is *narrower* than your
text. A **narrow** synonym matching means it is *broader*. Those are different
mistakes, and the scope tells you which one you are about to make.

**Exit if** the exact probe returns exactly one term — on any channel — and
`$OQ term` on it shows nothing in the record contradicting the context: wrong
taxon, wrong stage, a definition about a different sense of the word.

One term, not one strong-channel term. If several come back you have rivals and
must adjudicate, even when only one matched a label or exact synonym. `skin`
returns four; `zone of skin` is the only exact-synonym hit, but `skin of body`
is a real rival.

If exact returns nothing or several, add the stemmed probe:

```
$OQ lexical -q "<string>" -o <ontology> --probes exact,stemmed
```

Tokenised and stemmed — `muscles` and `muscle` behave identically — with
definitions excluded. Good recall, untrustworthy ordering.

`rank` is reported and is worth exactly this much: it separates match channels
reliably, and it is unreliable within the lexical band (`skin of body` ranks
46th, `muscle organ` 360th). Never choose on it.

`--probes definition` adds terms matching only in their definition text — about
40% of a result set. Those are leads, not candidates, and do not satisfy the
exit test on their own.

**Go to rung 2 if**: exact gave nothing; exact gave more than one term; or the
stemmed probe returned hundreds of terms all more specific than your string
(`skin` returns 121, `muscle` 768). That is recall working correctly, and the
job from here is reduction.

### Rung 2 — names the ontology might actually use

Before querying, write down several candidate names. Use what you know about
how ontologies word things: formal over colloquial; `system`, `tract`, `region`,
`zone` as head nouns; Latinate alternatives; singular; species-neutral.

For `full reproductive tract`: reproductive system, reproductive tract, female
reproductive system, genital tract, reproductive organ system.

**Substitute words inside the name, one at a time.** This is the single most
productive move at this rung and it is easy to skip, because the string you
were given already looks like a term. Hold the rest of the name fixed and swap
one word for the ontology's preferred wording:

| you were given | also try |
|---|---|
| future X | presumptive X, X primordium, X anlage, X rudiment, X bud, developing X |
| control of X | regulation of X, X regulation |
| X formation | X development, X morphogenesis, X differentiation |
| upper / lower X | fore- / hind-, superior / inferior, cranial / caudal X |
| X layer | X lamina, stratum X, X zone |

**Do not expect the ontology's synonyms to do this for you.** They mostly do
not. In Uberon, 39 terms are named `future X` and 44 `presumptive X`, and only
**9 of each** carry the other spelling as an exact synonym — so searching
`future midbrain` returns nothing while `presumptive midbrain` is a real term.
In GO, **3161** terms are named `regulation of X` and exactly **4** carry a
`control of X` synonym. A curator who writes "control of glycolysis" finds
nothing by searching, and finds the term immediately by substituting one word.

The substitutions worth trying come from the *kind* of thing you are naming, so
work out the kind first. An anatomical precursor, a regulatory process and a
cell layer each have their own vocabulary, and guessing across kinds wastes
queries.

**Combine fields here**, and do it before reaching for the graph. If the record
has more than one search-term field, some candidates should be those fields
joined the way an ontology would word them. `spine` plus `thoracic` gives
`thoracic spine` and `thoracic vertebral column`, both exact synonyms of one
Uberon term — no graph query needed.

Also write down what *shape* you expect the answer to have: "a part of the eye",
"a grouping term over two named structures", "a stage term with a week number".
The shape tells you which rung-3 move to make if this fails.

```
$OQ lexical -o <ontology> --probes exact -q "<name1>" -q "<name2>" -q "<name3>"
```

All candidates in one invocation. Exit on the same test as rung 1.

A multi-token query is conjunctive and strict: `full reproductive tract` returns
**zero** because no term carries all three tokens. That is informative — drop
the weakest token and try again rather than concluding the term does not exist.

**Go to rung 3 if**: nothing came back for any candidate; every hit is more
specific than the input; or the hits each cover only *part* of the input
(`Cornea/Conjunctiva` returning cornea terms and conjunctiva terms separately).

### Rung 3 — structural

The failure signal chooses the move. Do not run all of them.

**Hits all too specific, or each covering only part of the input** → common
ancestors.

```
$OQ common-ancestors -s <CURIE> -s <CURIE> -t <ontology>
```

**Choosing the seed set is the judgement this tool cannot make**, and it decides
everything. Two quite different situations:

- *Co-annotation* — the seeds genuinely describe one thing (a sample annotated
  `Cornea/Conjunctiva`; a set of cell types from one dataset). The set comes
  from the data, so the common ancestor **is** the mapping.
- *Hit set* — the seeds merely share a word. This is a discovery move, telling
  you which region of the ontology your word lives in. Its output is candidates
  to inspect, never an answer.

For a hit set, **never pass the whole thing in.** Read the hits, decide how many
distinct senses are present, and run the query once per coherent sense. All 75
Uberon `muscl*` terms together give `anatomical structure`; split by sense, the
gut layers give `muscular coat` and the body-region muscles give a band around
`skeletal musculature`. The whole 768-term set would simply time out.

**Read the shape of the IC column, not the top row:**

- *One clear winner.* Cornea + conjunctiva → `ocular surface region` at 57.29,
  next at 44.61. Take it.
- *A band, then a cliff.* Glycolysis + TCA cycle → four candidates between
  56.75 and 60.34, then a 39-point drop. The band is your shortlist.
- *A low ceiling.* Cornea + femur → nothing above 33.75, on a cross-cutting
  grouping class. These share no meaningful ancestor, which is itself an answer.

IC is comparable within one result set only — never across ontologies or
queries.

**Read `missing_seeds`, not just the full-coverage rows.** A candidate that
misses one or two seeds and outranks everything on IC usually means your
partition is wrong. `zone of skin` has the highest IC of anything returned for
the 82 skin-zone seeds and covers 81 — and the seed it misses is `skin of body`,
which should not have been in the set. The command warns when this happens.

The traversal covers **part_of as well as subclass**, and for grouping terms the
part_of leg does the work — in GO as much as in Uberon. If a result looks like
nothing but `anatomical structure` or `metabolic process`, check whether
`--predicates` dropped part_of.

**You need the inhabitants or parts of a structure** →

```
$OQ relations <CURIE> -p part_of -d in -t <ontology>
```

`in` is what points at the term, `out` is what the term points at. Use part_of
for cells in a region; `located_in` returns nothing in practice. `overlaps` is a
looser alternative worth trying.

**You need to learn how the ontology words a family of things** →

```
$OQ cohort -o <ontology> --label-contains "<word>"
$OQ cohort -o <ontology> --sibling-of <CURIE>
```

Do this *instead of* guessing at abbreviations. Human developmental stage terms
are labelled `9th week post-fertilization stage` and carry **no synonyms at
all**, so no amount of trying `12 pcw`, `wk 12` or `12 weeks PCF` will hit one.
Read the convention off twenty real labels and construct the string.

**The target ontology is not in Ubergraph** → you still have

```
$OQ neighbours <CURIE> -o <ontology>      # one-hop asserted relations
$OQ hierarchy <CURIE> -o <ontology> -d up|down
$OQ crosswalk <xref-CURIE> -t <ontology>  # bridge into a resident ontology
```

`neighbours` is how EHDAA2's staging link surfaces
(`existence starts during or after → HsapDv:0000019`); it exists nowhere else.
`hierarchy` fetches both subsumption and hierarchical walks and reports the
difference, which matters: EHDAA2 liver has 0 descendants by subsumption and 26
with part_of.

**You need to know what else a term is called elsewhere** →

```
$OQ xrefs <CURIE> -o <ontology>
```

Treat an xref as a pointer, not as equivalence. SKOS mappings, reported
separately, are the stronger claim.

### Rung 4 — adjudicate

```
$OQ term <CURIE> -o <ontology>
```

On a shortlist of no more than about five. For each, read:

- the definition, against the original string;
- the logical axioms — often more decisive than the definition;
- the synonyms with their scope;
- `in taxon` and stage links, against whatever you called a validator.

A validator contradiction is evidence to report, not a gate to apply silently.
Computed taxon constraints are sometimes wrong. Say what it said and what you
did about it.

### Rung 5 — unresolved

A legitimate outcome and far better than a confident wrong answer. Two laps
through rungs 2–4 with nothing new learned means rung 5, not a third lap.

## The exit test

Before reporting a term, write one line: **why this term and not its nearest
rival.**

- Cannot name a rival → you have not looked at enough. Go back.
- Can name one but cannot separate them → report both, or escalate a rung to
  find something that separates them.
- The only evidence is a related- or broad-synonym hit, or a definition-only
  match → not sufficient on its own. Find a second, independent line.

**Two independent channels agreeing is the strongest evidence available.** `skin`
reaches `skin of body` twice over: as a related synonym, and as the top
full-coverage common ancestor of the 82 skin-zone terms. Those routes share no
assumptions. When you can say that, say it.

If you cannot write that line, you have not finished, however good the match
felt.

## Report

For each record:

- the CURIE and label, or `unresolved`
- the one-line why-this-not-that
- which rung you exited at
- the runners-up you rejected, each with a short reason
- any validator that flagged rather than rejected, and what you did
- anything in the input you could not account for
- where a graph move was unavailable because the ontology is not in Ubergraph

The rejections are the audit trail. A mapping without them cannot be debugged
six months later, which is the state this skill exists to get out of.
