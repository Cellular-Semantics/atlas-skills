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

## The tool

Every invocation looks like this. Keep the quotes — an unquoted command in a
variable does not word-split under zsh, which is the default shell on macOS:

```
uvx --from "${OQ_FROM:-git+https://github.com/Cellular-Semantics/atlas-skills@pkg-onto-query--v0.3.0#subdirectory=packages/onto-query}" oq <command>
```

That default is the pinned release and is what you should normally run. If
`$OQ_BIN` is set in the environment, run `"$OQ_BIN" <command>` instead — a
project developing `onto-query` points it at a local build. In that case
`oq --version` reports something other than the pinned version, and any
behaviour you record is that build's rather than the release's, so say which
you ran.

**This skill needs onto-query 0.3.0 or later.** It uses `--compact`,
`--direct`, `cohort --text-contains`, `cohort --under`, predicate CURIEs on
`relations -p`, and `term` over several CURIEs at once, none of which exist
before 0.3.0. Check with `$OQ --version` if a command is rejected for an
argument this document tells you to pass.

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

Once per ontology per session, before any of the stages:

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

## How the work is shaped

Five stages, and the order is the whole point:

**Prepare → Find → Prune → Confirm → Judge.**

- **Prepare** reads the record and builds the string you will search, plus the
  context you will judge against. No query runs.
- **Find** generates candidates. Several moves, cheapest first; the signal from
  the last failure chooses the next one.
- **Prune** reads candidate *names* and throws away the ones that are obviously
  the wrong kind of thing. Cheap, and it is where most of the reduction happens.
- **Confirm** pulls full detail on the survivors and checks them against the
  context.
- **Judge** picks one, or reports that nothing fits.

One rule holds the shape together: **never pull detail on a candidate you could
have rejected from its name.** A wide result set is read, not fetched. Measured
on Uberon `skin` — 121 hits, 33.7 kB — the labels are 4.0 kB of that and the
definitions and synonym sets are 17.8 kB. Reading 121 labels to keep three is
cheap; fetching 121 full records to keep three is not.

Two things to avoid throughout, because they are the failure modes this exists
to replace:

- Picking a term because it came back first. No relevance score is returned to
  you. Rank, where it is reported, is a loose signal only.
- Mechanically transforming the input string — stripping, splitting, stemming —
  and searching the fragments. Work out what the text *means*, then work out
  what the ontology probably *calls* that.

Spending heavily on an easy record is as much a failure as getting a hard one
wrong. Most records are settled by Find and Prune alone.

---

## Stage 1 — Prepare

Read the whole record, all fields together. Nothing is queried here, and most
of the decisions that settle a hard record are made here. A query cannot
recover a string that was never assembled.

### Could a plain lexical match get this wrong?

Signals that it could: more than one field; the string names more than one
thing (`Cornea/Conjunctiva`); it carries a number, unit or abbreviation
(`12 pcw`, `wk 8`); it is a short common ambiguous word (`skin`, `muscle`,
`brain`, `cortex`); it reads as a description rather than a name
(`full reproductive tract`).

### Is the string searchable at all?

Ask it concretely: could a curator find this term by typing this string into a
search box? If the answer is no, no lexical probe will help, and **Find and
Prune are not a cheap first try — they are a waste that produces false leads.**

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
   advice document covers it yet, read the convention off the ontology:
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

### Write the string you are going to search

One string, constructed, not copied. It is often *several fields joined the way
an ontology would word them*, and that joining is the single most productive
move available before a query runs:

| record | the string to search |
|---|---|
| `structure=spine`, `region=thoracic` | `thoracic spine` — an exact synonym of `UBERON:0006073` |
| `bone=frontal`, `anatomical_site=calvaria` | `frontal bone` — the key types the value |
| `obs_tissue=spinal cord; brachial` | `brachial spinal cord` — not two structures |
| `obs_tissue=brain; stroma` | `stroma of brain` — the second part modifies the first |
| `tissue=cortex`, `organ=kidney` | `kidney cortex` — an exact synonym of `UBERON:0001225` |

Say which fields went into it. If two readings are both plausible, write both
strings and probe both — that costs one invocation, because `-q` repeats.

A separator is not an instruction to split. `brain; stroma` and
`spinal cord; brachial` are each one structure with a modifier, and mapping the
halves independently gives two wrong answers rather than one. Both spellings
appear in real corpora, which is how you can tell the separator is doing no
semantic work.

### Write the context you will judge it against

Everything that did not go into the string, each item tagged with *when it gets
used*. The tag names the stage that reads it, so a tag nothing reads is a tag
worth deleting:

- **Disambiguates** — consumed *now*, while building the string. One field
  settling what another one means. `Subregion=Thalamus` is ambiguous between
  the dorsal thalamus and the union; `obs_tissue=dorsal plus ventral thalamus`
  settles it, and the settling happens before the query, not after.
- **Discriminates** — held back for Confirm, to separate rivals, and to supply
  a region to search inside if Find stalls. **Gross anatomical location belongs
  here, and it is the most useful thing in the block.**
- **Validates** — checked against the chosen term at Confirm. Species,
  developmental stage.
- **Unexplained** — nothing accounts for it yet. Goes in the report.

**Composing is not filtering, and location can do either.** A field goes into
the string when the fields *together name one structure* — `spine` + `thoracic`
is `thoracic spine`, `kidney` + `cortex` is `kidney cortex`. A field stays in
the context block when it merely describes circumstances the term is not named
after. The test is whether a curator would write the joined phrase on a slide
label.

Get this backwards and you get nothing back, because a multi-token query is
conjunctive and strict: every token must appear somewhere in the term. Adding
`human`, `adult` or `10x` to a query is how a real term returns zero hits.

**Sex is the exception** — the one piece of context that genuinely constrains
rather than discriminates, and latent knowledge usually settles it without a
query. A record marked female does not need the graph to rule out
`prostate gland`.

Finally, write down what *shape* you expect the answer to have: "a part of the
eye", "a grouping term over two named structures", "a stage term with a week
number". The shape tells you which Find move to reach for when the first one
fails.

---

## Stage 2 — Find

Generate candidates. The moves are listed cheapest first, but this is a menu,
not a staircase: **the last failure signal chooses the next move.** Do not run
them all.

### The exact probe

```
$OQ lexical -q "<string>" -o <ontology> --probes exact --compact
```

Whole-string match against the label or any synonym, case-insensitive. Search
**the string Prepare built**, not the raw field value, and probe every plausible
reading in the one invocation.

Each hit reports which field matched, in `found_by.exact.matched_fields`:

```
UBERON:0000014  zone of skin    exact_synonym
UBERON:0002097  skin of body    related_synonym
UBERON:0001003  skin epidermis  broad_synonym
UBERON:0002199  integument      related_synonym
```

**The channel is the part of this result worth trusting.** Rank is not
comparable within the lexical band, but which field matched is reliable, and it
tells you the *grain* of what you found rather than merely that you found
something.

→ Hits came back: go to **Prune**, however few. One hit is not an answer.
→ Nothing came back: try the stemmed probe, or go to another Find move.

### The stemmed probe

```
$OQ lexical -q "<string>" -o <ontology> --probes exact,stemmed --compact
```

Tokenised and stemmed — `muscles` and `muscle` behave identically — with
definitions excluded. Good recall, untrustworthy ordering. `rank` separates
match channels reliably and is unreliable within the lexical band (`skin of
body` ranks 46th, `muscle organ` 360th). Never choose on it.

Hundreds of terms all more specific than your string (`skin` returns 121,
`muscle` 768) is recall working correctly. That is a Prune problem, not a
failure.

`--probes definition` adds terms matching only in their definition text — about
40% of a result set. Those are leads, not candidates, and never sufficient on
their own.

### Names the ontology might actually use

Reach for this when the probes returned nothing, or returned only the wrong
kind of thing. Use what you know about how ontologies word things: formal over
colloquial; `system`, `tract`, `region`, `zone` as head nouns; Latinate
alternatives; singular; species-neutral.

For `full reproductive tract`: reproductive system, reproductive tract, female
reproductive system, genital tract, reproductive organ system.

**Substitute words inside the name, one at a time.** This is the single most
productive move here and it is easy to skip, because the string you were given
already looks like a term. Hold the rest of the name fixed and swap one word
for the ontology's preferred wording:

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

```
$OQ lexical -o <ontology> --probes exact --compact -q "<name1>" -q "<name2>" -q "<name3>"
```

All candidates in one invocation. A multi-token query is conjunctive and
strict: `full reproductive tract` returns **zero** because no term carries all
three tokens. That is informative — drop the weakest token and try again rather
than concluding the term does not exist.

### Search inside a region

Reach for this when the string is ambiguous on its own but the record says
where in the body the sample came from. This is what the *discriminates* tags
are for.

```
$OQ cohort -o <ontology> --text-contains "<word>" --under <REGION-CURIE>
```

It narrows before any name is read, which makes it cheaper than pruning a wide
result by hand: `cortex` matches 150 Uberon labels and 14 of them are inside
the kidney.

**Use `--text-contains`, not `--label-contains`.** The string a record carries
is very often not the label. `UBERON:0006073` is labelled "thoracic region of
vertebral column" and carries `thoracic spine` only as a synonym. Measured:
`spine` under `UBERON:0001130 vertebral column` gives 10 terms by label and
none of them regional, against 16 by label-or-synonym including the cervical,
thoracic and lumbar regions. All three are reachable only through a synonym,
and they are exactly the terms a record saying "spine" wants.

`--label-contains` is for the other job — reading a naming convention off real
labels, where a synonym is noise. Human developmental stage terms are labelled
`9th week post-fertilization stage` and carry **no synonyms at all**, so no
amount of trying `12 pcw`, `wk 12` or `12 weeks PCF` will hit one. Read the
convention off twenty real labels and construct the string.

### Common ancestors

Reach for this when every hit is more specific than the input, or when the hits
each cover only *part* of it (`Cornea/Conjunctiva` returning cornea terms and
conjunctiva terms separately).

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
`--predicates` dropped part_of. Unlike `relations`, this command takes only its
curated predicates, because information content is comparable between rows only
when every row came from the same traversal.

### Parts and inhabitants of a structure

```
$OQ relations <CURIE> -p part_of -d in -t <ontology> --direct
```

`in` is what points at the term, `out` is what the term points at. Use part_of
for cells in a region; `located_in` returns nothing in practice. `overlaps` is a
looser alternative worth trying.

`-p` takes **any predicate CURIE**, not only the shorthand names — `RO:0002170`
for `connected to`, `RO:0002134` for `innervates`. To find out what a term
actually carries, run `$OQ term` on it: the predicates come back with their
CURIEs, ready to pass straight back here.

**`--direct` matters.** Without it you get Ubergraph's transitive closure, not
asserted edges: `UBERON:0002240 develops_from` gives 1 edge direct and 29
through the closure, mostly upper ontology. Direct first; closure only when the
direct edge leads somewhere unusable.

### Outside Ubergraph

```
$OQ neighbours <CURIE> -o <ontology> -p <PREDICATE> -t <TARGET>
$OQ hierarchy <CURIE> -o <ontology> -d up|down
$OQ crosswalk <xref-CURIE> -t <ontology>
$OQ xrefs <CURIE> -o <ontology>
```

`neighbours` is how EHDAA2's staging link surfaces
(`existence starts during or after → HsapDv:0000019`); it exists nowhere else.
`hierarchy` fetches both subsumption and hierarchical walks and reports the
difference, which matters: EHDAA2 liver has 0 descendants by subsumption and 26
with part_of. Treat an xref as a pointer, not as equivalence; SKOS mappings,
reported separately, are the stronger claim.

`neighbours` reads incoming relations from an OLS4 endpoint that deduplicates
edges by source and target, so if two predicates point at a term from the same
source only one is shown. It warns when this applies. Outgoing relations are
not affected.

---

## Stage 3 — Prune

Read the candidate names and throw away what is obviously the wrong kind of
thing. No further query. Everything you need is already in the result.

**One hit is not an exit.** A count is the weakest signal available, and on its
own it will walk you into a wrong answer without raising anything. `cortex`
against Uberon returns **exactly one** exact hit: `UBERON:0001851 cortex`,
defined as *"Outermost layer of an organ"*, whose only parent is `organ part`.
It is a generic grouping class. Almost no record that says "cortex" means it.
The count comes out at one, the single hit looks clean, and nothing in the
result says you are about to be wrong.

Screen on:

- **The sense of the word.** Does the name describe the thing the record means,
  or a different sense? `Outermost layer of an organ` is not a brain region.
- **Grouping class or structure?** A bare one-word label sitting under
  `organ part`, `anatomical structure` or `organ component` is the tell. These
  exist to classify, not to annotate with.
- **Which channel matched, and how much of your string it consumed.** A
  **broad** synonym matching your text means the term is *narrower* than your
  text. A **narrow** synonym matching means it is *broader*. Those are different
  mistakes. A hit arriving **only** on narrow synonyms is a signal in itself:
  the ontology has a broader grouping term and nothing at the grain you asked
  for — `frontal bone` reaches `UBERON:0000209 tetrapod frontal bone` that way.
- **Grain.** A result full of terms far more specific than your string means
  your string is a grouping term, and the answer is probably their common
  ancestor rather than any one of them.

→ Survivors: go to **Confirm**.
→ Nothing survived: back to **Find**, with what you learned about why. A single
hit that fails the screen is a Find trigger like any other, and it is the one
most easily mistaken for success.

There is no limit on how many candidates may survive. If a shortlist feels
unmanageably large, the problem is not its length — it is that you cannot yet
say what distinguishes its members, and that is a Prepare problem. Go back and
work out what the record actually says.

---

## Stage 4 — Confirm

Pull full detail on the survivors, in one call, and check them against the
context.

```
$OQ term <CURIE> <CURIE> <CURIE> -o <ontology>
```

Pass the whole shortlist. Adjudication is comparison, not lookup: what separates
candidates is usually a contrast between them — this one is part of the kidney
and that one of the collecting duct system; this one carries a taxon restriction
the record contradicts — and a contrast is visible side by side and has to be
reconstructed when each is fetched alone.

For each, read:

- the definition, against the original string;
- the logical axioms — often more decisive than the definition;
- the synonyms with their scope;
- `in taxon` and stage links, against whatever you tagged *validates*.

Then bring in the items you tagged **discriminates**, location above all, and
ask whether each candidate sits where the record says it sits. This is what
decides `cortex of kidney` against `cerebral cortex`, and it is the stage those
tags were written for.

Check `found` on every block. An empty block means one of three things and they
call for different responses: the ontology is not in Ubergraph, the CURIE is not
in the ontology you named, or the term genuinely carries no axioms. The warnings
say which.

A validator contradiction is evidence to report, not a gate to apply silently.
Computed taxon constraints are sometimes wrong. Say what it said and what you
did about it.

---

## Stage 5 — Judge

Before reporting a term, write one line: **why this term and not its nearest
rival.**

- Cannot name a rival → you have not looked at enough. Back to Find.
- Can name one but cannot separate them → report both, or make one more Find
  move aimed specifically at what would separate them.
- The only evidence is a related- or broad-synonym hit, or a definition-only
  match → not sufficient on its own. Find a second, independent line.

**Two independent channels agreeing is the strongest evidence available.** `skin`
reaches `skin of body` twice over: as a related synonym, and as the top
full-coverage common ancestor of the 82 skin-zone terms. Those routes share no
assumptions. When you can say that, say it.

If you cannot write that line, you have not finished, however good the match
felt.

**Unresolved is a legitimate outcome** and far better than a confident wrong
answer. Two passes through Find and Prune with nothing new learned means
unresolved, not a third pass.

---

## Report

For each record:

- the CURIE and label, or `unresolved`
- the one-line why-this-not-that
- which Find moves you used, and which one produced the answer
- the runners-up you rejected, each with a short reason
- any validator that flagged rather than rejected, and what you did
- anything in the input you could not account for
- where a move was unavailable because the ontology is not in Ubergraph

The rejections are the audit trail. A mapping without them cannot be debugged
six months later, which is the state this skill exists to get out of.
