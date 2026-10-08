# Brief: review rungs 0 and 1 of the mapping ladder

Starting document for a session on the `ladder-review` branch. Written to be
picked up cold.

## The two questions

1. **Is rung 0 sufficient for *preparing* a query?** It currently triages — can
   lexical fail, is the string searchable, what role does each field play. The
   question is whether triage is the same thing as preparation.

2. **Is rung 1's exit test too restrictive?** It exits only when the exact probe
   returns exactly one term, on any channel. The question is whether a weighted
   reading — of which channel matched, and how much of the query string it
   consumed — would serve better than a count.

Everything below is input to those questions. None of it is a conclusion.

---

## Read this part first: how this work is to be tested

This is here before the investigation deliberately. The previous piece of work
on this skill produced confident numbers about the wrong thing, and the cause
was that the testing shape emerged as the work went rather than being fixed
first.

**The unit is a record and the thing under test is the skill.** Not a string,
not a query, not a function. A result that is true of a mechanical stand-in is
not a result about the skill.

**Use the harness that already exists.** `evals/runner.py` runs cases against
the *installed plugin* in a fresh temporary directory, with no project
`CLAUDE.md` and no `.claude/skills` in scope. Case layout, from
`evals/cases/read-obs-once/`:

```
evals/cases/<name>/
  prompt.md        the user turn, verbatim
  checks.json      {"tags": [...], "checks": [{"kind": ..., "pattern": ..., "why": ...}]}
  graders/         criteria for LLM grading where a pattern will not do
```

`checks.json` kinds in use: `command_matches`, `command_not_matches`,
`answer_any_of`. Each check carries a `why`, and the `why` is the part that
makes a failing case diagnosable.

```
python3 evals/runner.py --dry-run          # prints prompts, spends nothing
python3 evals/runner.py --case 'rung0-*'
```

Cases cost real money (~$0.20–0.50 each). `--max-cost-usd` aborts a runaway
suite.

**If that harness cannot run here, say so and stop.** Do not build a substitute
and measure the substitute. The previous work built a mechanical string matcher,
measured it, and published "47 refutations, 92% false positive" as though it
described the method. It described the matcher.

**Name the cases before looking at any result.** Commit `prompt.md` and
`checks.json` first. Do not add, drop or reword a case after seeing how it went.

**No percentage on anything that is not the real thing.** A proxy may inform
judgement; it may not produce a statistic.

**Label every claim** as *verified* (a tool said so and the command is in the
transcript), *judged* (a person decided, and the reasoning is written down), or
*assumed*. The previous work blurred these and the blurring is what let a
selected sample be quoted as a rate.

**Checkpoint with the user before publishing any number**, not after.

---

## Question 1 — rung 0

### What rung 0 currently does

Read it in full in `SKILL.md`; in summary it asks three things. Could a plain
lexical match get this wrong. Is the string searchable at all — with a good
table of the cases where it is not (quantities, identifiers) and a
`convert, construct, verify` route for those. And what is each field for, with
every field given exactly one role: search term, structural constraint, or
validator.

### The observation that prompted the question

Nineteen HDCA records were worked by hand from whole record to Uberon CURIE
(archived: `docs/archive/ehdaa2-investigation/results-end-to-end.md`). **Those
records were selected for being hard, so nothing below is a frequency claim.**

What decided them was, repeatedly, a move made *before* any query:

- **Combining two fields into one name.** `region=thoracic` with
  `obs_tissue=spine; thoracic` is `thoracic spine`, an exact synonym of
  `UBERON:0006073 thoracic region of vertebral column`. One lexical call, no
  graph.
- **Letting one field disambiguate another.** `Subregion=Thalamus` is ambiguous
  between the dorsal thalamus and the union; `obs_tissue=dorsal plus ventral
  thalamus` settles it. Likewise `dissection=Mesencephalon` against three
  sibling fields all reading `Midbrain`.
- **Recognising a component as a modifier, not a structure.** `brain; stroma`
  means stroma *of brain*. `spinal cord; brachial` is the brachial spinal cord.
  Splitting on the separator and mapping the parts independently is wrong, and
  both spellings appear in the corpus, which is how you can tell.
- **Reading a field key to learn what a value is.** `bone=frontal` beside
  `anatomical_site=calvaria` makes `frontal` the frontal bone. Guessing from
  study context made it the frontal cortex, which was wrong.

Of these, only the first appears anywhere in the skill — and it is in **rung 2**,
after the first query has already been run.

### Things worth establishing

- Does rung 0 as written cause a reader to *build the string they will search*,
  or only to decide whether searching is safe?
- The field-role assignment (search term / structural constraint / validator) is
  one role per field. Is that right when two fields compose into a single name?
  `spine` and `thoracic` are not two search terms; they are one.
- Is there a missing instruction of the form "before querying, write the string
  you are going to query"? If so, does it belong in rung 0 or does rung 2 need
  to move earlier?
- The `convert, construct, verify` route for quantities is the strongest part of
  rung 0 and it works. Is there an analogous route for composites?

---

## Question 2 — rung 1

### What rung 1 currently does

The exact probe matches the whole string against label or any synonym, and
reports which field matched in `found_by.exact.matched_fields`. The skill says:

> **Exit if** the exact probe returns exactly one term — on any channel — and
> `$OQ term` on it shows nothing in the record contradicting the context.

and notes that a broad synonym matching means the term is narrower than your
text, a narrow synonym matching means it is broader.

### The observation that prompted the question

Three lookups from the same run, all of which the current rule treats alike:

| query | result | channel | what it actually means |
|---|---|---|---|
| `thoracic spine` | `UBERON:0006073` thoracic region of vertebral column | exact_synonym | clean hit, exit |
| `eye` | `UBERON:0000970` eye, `UBERON:0000019` camera-type eye | label, then broad_synonym | two terms, needs thought |
| `frontal bone` | `UBERON:0000209` tetrapod frontal bone | **only** narrow synonyms | the species-specific term may not exist |

The third is the interesting one. A hit that arrives *only* on a narrow-synonym
channel is a signal in its own right — the ontology has a broader grouping term
and no term at the grain you asked for. The current rule reads it as "one term,
exit".

### Things worth establishing

- Is a weighted reading better than a count? Candidate weights: which channel
  matched (label > exact synonym > narrow/broad > related), and how much of the
  query string the match consumed.
- The skill already says rank is untrustworthy within the lexical band but
  reliable *between* channels. If that is true, the channel is already a usable
  weight and the exit test is discarding it.
- Does "exactly one term" ever fire in practice on real records, or do most
  records return zero or several? If it rarely fires, the rule is not doing the
  work its prominence implies.
- What is the cost of a looser exit — more rung-2 and rung-3 work, or more wrong
  answers? These are different failures and the review should say which it is
  trading.

---

## What you have to work with

- `plugins/onto-mapping/skills/map-to-ontology/SKILL.md` — the ladder itself.
- `docs/onto-query-gaps.md` — five `oq` changes already specified, with
  evidence. Start here before proposing tool changes; three of the five are
  about making generic graph navigation parameterisable rather than adding
  commands, which is the preferred direction.
- `evals/` — the harness, and `evals/ontology-mapping/` for the existing
  ontology cases (`cases-core.json` covers general ladder behaviour: whether the
  skill triggers, how far up the ladder it goes, whether it names a rival).
- `docs/archive/ehdaa2-investigation/` — record, not guidance. Its
  `results-end-to-end.md` is where the rung-0 observations come from, and its
  README records what was wrong with how that work was tested.

## Out of scope

- Rungs 2 through 5, unless a rung-0 or rung-1 change forces a consequential
  edit. The branch is deliberately narrow.
- EHDAA2, EMAPA, and developmental mapping generally — that is the
  `uberon-dev-survey` branch, running in parallel.
- `SKILL.md`'s HsapDv pointer and `references/hsapdv.md`.

## Coordination

`uberon-dev-survey` is running in parallel off the same base. It adds a new
reference document and scripts; it will eventually want a one-line `SKILL.md`
pointer. That pointer lands **after** this branch merges, so the only shared
file is touched once rather than twice.

## Known traps

- Ubergraph 500s and drops connections on large aggregate queries; retry with
  backoff rather than concluding the data is absent.
- `oq term` on an ontology Ubergraph does not hold returns an empty result with
  **no warning**, which reads as a term with no axioms.
- `oq relations` answers from the `redundant` graph — the transitive closure —
  so a "direct" edge is not what it returns. Direct edges are in `nonredundant`.
