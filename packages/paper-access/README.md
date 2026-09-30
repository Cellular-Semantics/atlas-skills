# paper-access

Retrieve the text of a list of papers and record honestly what arrived.

**Status: implemented, not yet released.** 139 unit tests, all offline —
every rung runs through an `httpx` MockTransport. The `uvx --from` lines in the
skill and its hooks pin to `pkg-paper-access--v0.1.0`, which does not exist
until the tag is pushed; until then use an editable install or a local path.

## The waterfall

```
JATS XML  →  ASTA index probe  →  open-access PDF  →  ask a person
```

JATS first because reading a whole paper beats retrieving from it, and because
article XML is the only source carrying reference markup, guaranteed document
order, and figure and table legends. ASTA second: much better than a local
corpus across many papers, worse on any one paper, and its snippets omit figure
legends entirely. PDF third: no reference markup, no guaranteed reading order
across a column boundary.

The ASTA probe runs for every paper whatever route served it. There is no API
field that reports snippet coverage, so probing is the only instrument, and the
band is what tells a later multi-paper search which papers it can reach.

## The CLI

```
paper-access resolve    --input <file> | --id <id>        → identifiers or candidates
paper-access fetch      --store <store> --id <id>...      → walk the waterfall
paper-access show       --store <store> --id <id>         → one record
paper-access report     --store <store> [--json]          → the corpus as a table
paper-access candidates --inputs <dir>                    → what in a drop zone is a paper
paper-access adopt      --store <store> --id <id> --file <path>
paper-access note       --store <store> --id <id> --text "..."
paper-access verify     --store <store>                   → re-resolve and re-check titles
paper-access check      <record.json>                     → schema + cross-field rules
paper-access check-refs <document> --store <store>        → identifiers cited vs. store
paper-access schema                                       → print the record schema
paper-access --version
```

`paper-access papers --store <store>` lists the identifiers, one per line, for
piping into something else. `fetch` also takes `--no-pdf` (keep a corpus to
tagged XML) and `--no-asta` (skip the probe).

Exit codes are meaningful, and the plugin's hooks depend on them: 0 success,
1 error, 2 "the thing you asked me to check does not check out". `resolve`
exits 2 when anything needs a person to confirm it.

Store layout: `<store>/<id-slug>/{availability.json, source/paper.jats.xml |
source/paper.pdf, source/paper.txt}`. Paths inside a record are relative to the
record, so a store can be moved.

## Verified against the live services

Fetching `10.1038/s41586-023-06812-z` reproduces the worked example exactly:
Europe PMC serves 398 KB of article XML, and the probe returns 3 snippets,
0 sections, 0 refMentions — `abstract_only` — for a paper that is open access,
sits in PMC, and carries 118 graph references. Nothing but the probe tells that
apart from a fully indexed paper.

## What harvests from where

Most of this exists already, in three places, and the job is convergence rather
than invention:

| from | what |
|---|---|
| `Cellular-Semantics/Atlas-reporter@dev`, `services/paper_fetch.py` | the waterfall, the record model, the negative cache, PDF text-quality checks |
| `Cellular-Semantics/Atlas-reporter@dev`, `services/asta_indexing.py` | the index-depth probe and its calibrated bands |
| `Cellular-Semantics/Atlas-reporter@dev`, `services/_jats_parser.py` | JATS parsing across publisher dialects |
| `Cellular-Semantics/citation-traverse`, `cite_traverse/europepmc.py` | `_parse_id` — DOI / PMID / PMCID normalisation and interconversion |

Their unit tests are fixture-driven and came across largely intact.

Two deliberate departures from the Atlas-reporter original:

- **`route` and `local_source` are separate.** A paper served only by ASTA has
  no bytes on disk, which the original schema could not express.
- **No `deep_research_client`.** The probe needs one `snippet_search` call; that
  is a small typed HTTP wrapper and an `ASTA_API_KEY`, not a research framework
  pinned to a branch.

## Requirements

- `ASTA_API_KEY` for the probe. Absent, the probe records `skipped` — which is
  not the same finding as `unindexed` and must never be reported as one.
- `PAPER_ACCESS_CONTACT_EMAIL`, or `git config user.email`, for the open-access
  resolver, which requires a contact address on every request.
