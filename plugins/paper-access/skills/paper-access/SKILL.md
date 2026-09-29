---
name: paper-access
description: Get the text of a list of papers and say honestly what arrived. Takes DOIs, PMIDs, PMCIDs or rough citations, resolves them to confirmed identifiers, walks JATS XML → ASTA index probe → open-access PDF, and writes tagged article XML to disk beside a per-paper availability record. Use when a project needs a corpus of papers before it can do anything else, or when you need to know which papers a question can actually be answered from.
---

# paper-access

Getting the text is the first thing a project needs and the thing most likely to
come up short. A real corpus splits roughly three ways: most papers arrive as
tagged article XML, a few are reachable only as a PDF or only through a search
index, and some are not reachable by any automated route at all. **The ones that
do not arrive are as much the output as the ones that do** — a list of six papers
with the free copy each can be found at is work a person can act on, where "22
papers, mostly retrieved" is not.

The record schema is the contract and documents its own fields. Print it with
`paper-access schema` and read that rather than looking for a field list here.

## Requirements

- `uv`, and network access to GitHub on first run.
- `ASTA_API_KEY` for the index probe. Without it the probe records itself as
  `skipped` and the ASTA rung cannot serve a paper — the waterfall still runs,
  you just lose one route and the coverage information.
- A contact address for the open-access resolver, which requires one on every
  request: `PAPER_ACCESS_CONTACT_EMAIL`, or the checkout's `git config
  user.email`. Without it that rung reports itself skipped and you will
  under-count what is retrievable.

## The waterfall, and why it is in this order

```
JATS XML  →  ASTA index probe  →  open-access PDF  →  ask a person
```

1. **JATS XML first** — Europe PMC, then the preprint servers. Reading a whole
   paper beats retrieving from it: within one paper there is nothing a ranker
   buys that reading the text does not already give. XML also carries reference
   markup, guaranteed document order, and figure and table legends, none of
   which survive the alternatives.
2. **ASTA second.** ASTA is much better than a local corpus at questions
   *across* many papers, and worse at any question about one paper, because its
   snippets omit figure and table legends entirely. So it is a fallback for
   content, not a preference.
3. **PDF third.** Text recovered from a PDF has no reference markup and no
   guaranteed reading order across a column boundary. It is usable, not
   equivalent. This ordering may change if PDF extraction improves; the record
   says which route each paper took, so nothing downstream has to assume.
4. **Ask.** A paper behind a subscription is not a puzzle to solve.

**The ASTA probe runs for every paper regardless**, including ones already
served as XML. It costs one call, it is the only instrument that reports
snippet coverage — no API field does — and the band is what later tells a
multi-paper search which papers it can actually reach. A paper can be open
access, sit in PMC, carry 118 graph references, and still have nothing in the
snippet index but its title and abstract.

## The mechanical half

Everything that touches bytes is in the `paper-access` CLI. Use it rather than
fetching papers yourself: a paper is megabytes and none of it should pass
through your context.

```bash
alias paper-access='uvx --from "git+https://github.com/Cellular-Semantics/atlas-skills@paper-access--v0.1.0#subdirectory=packages/paper-access" paper-access'

# Turn whatever the user gave you into identifiers. Exact DOIs, PMIDs and
# PMCIDs pass straight through; anything else comes back as a candidate.
paper-access resolve --input <file> --json
paper-access resolve --id "Gopee 2024 prenatal skin atlas" --json

# Walk the waterfall. Repeatable --id, or a whole list at once.
paper-access fetch --store <store> --id <id> [--id <id> ...] [--retry]
paper-access fetch --store <store> --input <file>      # one id per line

# One paper's record, with any inconsistency flagged.
paper-access show --store <store> --id <id>

# The whole store as a table: route, kind, ASTA band, size.
paper-access report --store <store> [--json]

# What in a drop zone could be a paper: the id each file declares, its opening
# title, its size. Recursive.
paper-access candidates --inputs <dir>

# Take one of those files in as a given paper.
paper-access adopt --store <store> --id <id> --file <path>

# Re-resolve every recorded identifier and check the title still matches.
paper-access verify --store <store>
```

`fetch` is idempotent and cheap to re-run: a paper already here is not
re-fetched, and a paper recorded as unreachable is not re-attempted until you
pass `--retry`. Run it over the whole list first and work from what comes back.

## Identifiers: the two-phase rule

Everything an agent gets wrong about a literature corpus, it gets wrong here. A
DOI that is one digit out resolves to a different paper, or to nothing, and
nothing downstream will ever catch it.

So identifiers enter a record by exactly two routes, and there is no third:

- **Given.** An exact DOI, PMID or PMCID the caller supplied. Taken as-is,
  recorded as `from: input`.
- **Returned.** An identifier an API returned, recorded with that API's name and
  the time it answered.

`resolve` on anything vaguer — a citation string, an author and a year, a title
fragment — returns **candidates**, marked `confirmed: false`, carrying the
title, authors, year and journal the search returned. `fetch` refuses a
candidate. Put the candidates in front of the user with the metadata that came
back and ask them to confirm, in one go rather than one at a time. A title that
looks right is not confirmation: two papers by the same group in the same year
on the same tissue is the normal case in this literature, not the exotic one.

**You never write an identifier into a record, and you never write a title,
author list, year or journal into one either.** The CLI writes the record; you
read it. A `PreToolUse` hook denies a Write or an Edit to any `availability.json`
for exactly this reason. If something about a paper needs saying that the CLI
cannot know — that a PDF is the accepted manuscript, that the DOI resolves to a
correction — use `paper-access note`, which writes the one free-text field the
record has.

The same rule governs what you say in prose. Every DOI, PMID or PMCID you put in
a report must be copied from a record, not recalled. `paper-access check-refs
<file> --store <store>` checks a written file's identifiers against the store
and is worth running before you hand anything over; with `PAPER_ACCESS_STORE`
set, a hook runs it for you.

## Reading a store

`report` gives you the shape of the corpus. Four things in it need judgement.

### Which file in a drop zone is which paper

A drop zone is a flat bag named however things arrived, and **most of what looks
like a paper in it is not one**: supplementary PDFs, figure packs and generated
reports all open with something that reads like a title. `candidates` gives you
each file's declared identifier, its opening title and its size.

The identifier is the discriminator, and its absence is the strongest signal you
get: a published paper's PDF or XML almost always carries its own DOI in the
front matter, and a supplement or a locally generated document does not. **Do
not promote a title alone into a match.** A file called `media-2.pdf` opening
`GarciaAlonso 2026 Pediatric` looks exactly like a paper and is a supplement;
adopting it files that content under a real paper's DOI. Where there is no
identifier, ask — even when the title looks convincing, and especially then.

The same paper often appears twice, as XML and as a PDF with the same DOI.
**Adopt the XML and leave the PDF**, for the reasons in the waterfall above.

### Whether a resolver's hit is the paper or a manuscript of it

`oa_candidates` carries each location's `version` and `host_type` verbatim. A
`submittedVersion` in a repository is the manuscript before peer review: the
science is usually the same, but the text is not the published text, so a quote
from it may not appear in the article a reader opens. Where a paper came from
one, **say so when you report the corpus**. It is a caveat a later reader cannot
recover from the text alone.

### Whether a PDF became something worth reading

`local_source.text_quality` says how much came out and shows the opening. A scan
of page images extracts to a few short fragments; a paper extracts to tens of
thousands of characters in whole sentences. The CLI flags the blatant case, but
read the sample — text of the right size that is still gibberish is a real
outcome.

### What an ASTA-only paper is missing

`route: asta` means there are no bytes on disk and the content is reachable only
by querying the index. Two consequences, and both belong in what you report:

- **No figure or table legends.** ASTA does not index them. Cell-type naming
  information appears in a legend and nowhere else often enough that this
  matters; `has_figure_legends: false` is on the record to make it unmissable.
- **Nothing to read whole.** Anything downstream that expects a file will not
  find one. Test for `local_source`, not for a successful-looking `route`.

A band of `skipped` is not a band. It means the probe could not run — usually a
missing `ASTA_API_KEY` — and nothing at all was learnt about that paper's
coverage. Do not report it alongside `unindexed` as though they were the same
finding.

## When to stop and what to ask for

When every rung has run, stop. Do not go looking for the PDF yourself: the hosts
that block the CLI block you too. Report the papers with `route: none` as a
list, each with the free copy the record found (`gap.action` already names it)
and the `adopt` command to run afterwards. **Ask for all of them in one go.**

## Reporting a corpus

Give a table of identifier, route, kind and ASTA band, then the gaps. Say what
the routes mean rather than only naming them — `unpaywall / pdf` and
`europepmc / jats` are not the same quality of source, and an ASTA-only paper is
a third thing again. Be straight about the count: a corpus where six of
twenty-two papers need asking for is a normal result, and rounding it to "mostly
retrieved" hides work the user has to do.

## Supplementary material

Out of scope here, deliberately. A paper's supplements are fetched and indexed
by a separate skill that reads the JATS this one wrote — the article XML is
where the supplementary filenames and captions live, and they exist nowhere
else. Retrieve the papers first.
