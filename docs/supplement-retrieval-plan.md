# Plan: supplementary-material retrieval

**Phase 1 of two.** This phase gets the bytes and records honestly what arrived.
Inspecting and annotating what was retrieved is phase 2, deliberately
postponed — including what it does and where it lives — and will be its own PR.

Status: planned, nothing written. Branch `feature/supplement-retrieval`, cut
from `refactor/per-skill-plugins` (PR #3), which it depends on.

## Why this belongs in paper-access

Retrieval and annotation divide along a line that is already load-bearing in
this repo: **who is allowed to write the record.**

- **Retrieval produces machine facts** — filenames, the publisher's captions,
  bytes, digests, archive members, which route served each file, what is
  missing. Every one comes from an API or from disk. So it lives under the rule
  `availability.json` already has: written by the CLI, and a direct write
  denied outright by the existing `PreToolUse` hook.
- **Annotation produces judgement** — what a table is for, whether a sheet
  bears on the question, which spans of a prose document are worth reading.
  Those must be agent-written, so the strongest available guarantee is
  schema-plus-cross-field validation after the fact.

Two different guarantees, so two artefacts and two phases.

The dependency evidence points the same way. Of the four upstream modules:

| upstream module | imports |
|---|---|
| `supplement_fetch` | `httpx`, `curl_cffi`, `zipfile` |
| `supplement_store` | `openpyxl`, `zipfile` |
| `supplement_triage`, `supplement_prose` | stdlib only |

Retrieval needs **no new dependency** on top of what `paper-access` already
has: the same HTTP client, the same TLS impersonation, and stdlib zip.
`openpyxl` appears only where spreadsheets are read, which is phase 2. Folding
retrieval in costs nothing in install weight and inherits the Europe PMC
client, the negative cache, the `adopt` route and the gap-reporting pattern.

The coupling this creates is not coupling but cohesion: the paper's text and
the paper's supplements are the same paper, in the same directory, in one
record.

## Scope

**In:** discovering what supplementary files a paper has; fetching them;
unpacking archives; recording routes, digests, sizes and gaps; asking a person
for what no route reached.

**Out, and left to phase 2:** reading any supplement's *contents* — no
spreadsheet outlines, no prose extraction, no triage, no relevance verdicts, no
`tables`/`prose` sections. A retrieved file is an opaque blob with a caption.

**Out, permanently:** fetching from arbitrary external repositories. Where a
data-availability statement points at Zenodo, figshare, GEO or Dryad, that
pointer is recorded as a gap with its URL. Scraping unknown hosts is fragile,
and a named pointer is already actionable.

## The waterfall

Unlike the paper waterfall, where the rungs are alternatives, here the first
step produces a **listing** and the rest produce **bytes**. A listing is worth
having even when no bytes follow: it is the difference between "this paper has
eleven supplements we could not get" and "this paper appears to have none".

### Listing — what files exist

1. **JATS `<supplementary-material>`** — filenames *and* the publisher's
   captions, which exist nowhere else and frequently describe the contents
   better than anything recoverable from the bytes. Free: the XML is already on
   disk from `paper-access fetch`.
2. **Local text scan** — for a paper held only as a PDF, grep the recovered
   text for a data-availability statement. Yields pointers, not filenames.
3. **ASTA snippet search** — *only* where there is no local text at all, i.e. a
   record with `route: asta`. For those papers there is nothing on disk to
   grep, so a paper-scoped `snippet_search` for data-availability phrasing is
   the only way to find out where the material lives. Cheap, and the client is
   already in the package.
4. **bioRxiv supplement page** — a preprint has no PMC record, so steps 1–3 may
   all come up empty, but the preprint server lists its supplements with the
   author's own labels.

### Bytes — getting the files

5. **Europe PMC bundle** — one zip per article, members named exactly as the
   article XML lists them, so wanted files are extracted and the figure images
   that bloat the zip are skipped. Its virtue is needing no per-publisher
   knowledge at all.
6. **Publisher-direct** — per-file URL templates. Springer Nature only, because
   its ESM stem is derivable from the DOI alone. Others can be added when a
   corpus needs one; an absent template is a recorded skip, not a failure.
7. **bioRxiv** — serves each listed file individually, so step 4 supplies both
   the listing and the bytes.
8. **Manual** — a gap naming the file and where to get it. The only route for
   closed-access papers, and a first-class one.

Ordering and coverage come from probing a 22-paper corpus across Springer
Nature, Cell Press, AAAS, JCI, Wiley, Oxford, PNAS and a preprint. The article
XML served 14 of 22.

### Two traps to carry across verbatim

- **The bundle endpoint answers HTTP 200 with a 165-byte empty body** for a PMC
  paper whose full text is not open. Written naively that is an empty archive
  recorded as a success, and the paper reads as having no supplements. It must
  be detected and recorded as `unavailable`.
- **Size.** Observed bundles run 14–28 MB, but a 34-file PNAS paper exceeds
  60 MB and one atlas exceeds **445 MB** because of a supplementary video.
  Every cap must leave a trace in the record, never a silent absence: upstream
  uses a 250 MB bundle cap, an 80 MB per-member cap and a 512 MB cap for
  tabular members.

## What changes in the record

The upstream manifest already splits along this phase boundary, which is the
strongest evidence the split is a real seam and not a convenience:

| upstream `$defs` | phase |
|---|---|
| `SupplementFile`, `Retrieval`, `ArchiveMember`, `Gap` | 1 — retrieval |
| `TablePointer`, `Column`, `ProsePointer`, `ProseSection`, `CasUptake` | 2 — annotation |

So phase 1 adds a `supplements` block to `paper_availability.schema.json`
carrying the retrieval half, and phase 2 writes its own artefact beside it
rather than extending this one. `relevance` / `relevance_note`, which upstream
hangs on `SupplementFile` and `ArchiveMember`, are phase 2 and are **not**
ported now — a retrieval record that carried an unset relevance field would
invite a reader to treat "not yet judged" as "judged irrelevant".

**`schema_version` goes to 2.** A v2 reader must refuse a v1 record rather than
assume an absent `supplements` block means "no supplements" — that is exactly
the "we did not look" versus "there is nothing there" confusion the record
exists to prevent. There are only throwaway records in the testbed today, so
the migration is to refetch.

## CLI surface

A `supplements` subcommand group on the existing CLI, so there is one tool per
paper store:

```
paper-access supplements list    --store <s> --id <id>          what files exist, from the listing
paper-access supplements fetch   --store <s> --id <id> [--retry] walk the byte rungs
                                 [--no-bundle] [--max-bundle-bytes N]
paper-access supplements unpack  --store <s> --id <id>           expand archives, record members
paper-access supplements adopt   --store <s> --id <id> --incoming <dir>
paper-access supplements show    --store <s> --id <id>           the supplements block
paper-access supplements report  --store <s> [--json]            coverage across the store
```

Store layout extends the existing paper directory, so nothing new has to be
configured:

```
<store>/<id-slug>/
  availability.json          gains a `supplements` block
  source/paper.jats.xml      already there
  supplements/
    files/<file_id>/...      as the publisher packages them
    unpacked/<file_id>/...   archive members
    incoming/                where a person drops what they found
```

Every command prints JSON; `report` prints a table unless given `--json`. Exit
code 2 keeps its meaning: what you asked to be checked does not check out.

## What harvests, and what has to be split

| from `Atlas-reporter@dev` | lines | tests | disposition |
|---|---|---|---|
| `services/supplement_fetch.py` | 817 | 681 | port nearly whole |
| `services/supplement_store.py` | 1509 | 1015 | **split**: layout + unpack here, spreadsheet reading to phase 2 |
| `schemas/supplement_manifest.schema.json` | 503 | — | retrieval `$defs` only |
| `services/supplement_triage.py` | 604 | 595 | phase 2 |
| `services/supplement_prose.py` | 815 | 557 | phase 2 |

`supplement_store` is the fiddly part: it owns disk layout, archive unpacking
*and* spreadsheet reading. The first two come now, the third does not, and its
1,015 lines of tests divide with it. Everything else is a fairly direct port —
the upstream tests are fixture-driven and came across largely intact for
`paper-access`.

## Skills

`paper-access` gains a **second skill in the same plugin** rather than a second
job inside one SKILL.md. "Get me these papers" and "get the supplements for
these papers" are different asks, and a skill's description is its whole
trigger surface; one skill doing both blurs it.

This does not contradict one-skill-per-plugin, which is about *installability*:
anyone who wants supplements wants the paper, so the two are never wanted
apart. Same case as `cap-tools`.

Judgement the new skill owns, and which is the reason it is a skill at all:

- **A listing with no bytes is a result, not a failure.** Report the count and
  the gaps; do not round eleven unreachable supplements down to "none found".
- **Which dropped file is which supplement.** The `adopt` route needs a person's
  filenames matched to the publisher's labels, and the same warning applies as
  for papers: a convincing-looking title is not a match.
- **Whether a pointer is worth chasing.** A data-availability statement naming
  an accession is a gap with an action; it is not something to scrape.
- **When to stop.** Every rung has run, and the hosts that block the CLI block
  you too.

## Hooks

Nothing new. The existing `deny_record_write.py` covers `availability.json`,
and the supplements block lives inside it, so retrieval is protected by the
hook already shipped and tested. Phase 2 will need its own validator for its
own agent-written artefact.

## Tests

- **Package, offline.** Every rung through an `httpx` MockTransport, as for the
  paper waterfall. Fixtures needed: a JATS file with `<supplementary-material>`
  elements, a real-shaped Europe PMC bundle zip, the 165-byte empty-body
  response, an oversized member, and a bioRxiv supplement page.
- **The traps get named tests.** An empty-body bundle recorded as
  `unavailable`; a capped member recorded as a gap naming its size; a listing
  that survives a total byte failure.
- **Hook contract.** Already covered by `tests/test_plugin_hooks.py`; add a case
  that a write to an `availability.json` carrying a supplements block is denied
  just the same.
- **CI.** Add `paper-access` to nothing — it is already installed and tested.
  `skill-pins-resolve` picks up the new skill's pin automatically because it
  greps `plugins/`.
- **Behaviour.** In the testbed, from the branch on GitHub. The honest-reporting
  judgement above is exactly what a unit test cannot reach.

## Release

Package to **0.2.0**, plugin to **0.2.0**, tag `pkg-paper-access--v0.2.0`, and
update the pin in the new skill *and* the existing one in the same commit — the
two skills share a package, so they must not disagree about its version.

The CLI contract changes only by addition, so no consumer breaks. The record
schema change is breaking, which the `schema_version` bump states.

## Risks

- **`supplement_store` splits badly.** The 1,509-line module may turn out to
  have layout and spreadsheet logic entangled rather than merely adjacent. If
  so, port the layout half as new code against the same tests rather than
  carving the original.
- **Publisher templates rot.** Only Springer is implemented and URL patterns
  change. A template that stops working must record `failed`, not
  `unavailable`, so it is retried rather than believed.
- **The ASTA listing rung may earn nothing.** It is cheap, but a
  data-availability statement found in a snippet may name an accession rather
  than a file. That is still worth recording as a pointer; if it turns out to
  add nothing over the other rungs on a real corpus, drop it and say so.
- **Size caps and honesty.** The 445 MB case means a default cap will bite on
  real papers. Every cap needs its trace tested, not just implemented.

## Open questions

1. **Focus options are phase 2**, but if the retrieval listing should already
   record enough for a later focus choice — the caption, the media type, the
   size — then the schema needs to carry those from the start. I believe it
   does; worth confirming against a phase-2 sketch before tagging.
2. **Does `report` belong per-paper or per-store?** Both are useful; a store-wide
   coverage table is probably what a corpus needs first.
3. **Is a supplement worth a digest if it is never read?** Yes for change
   detection, but hashing a 445 MB video costs real time. Possibly cap hashing
   by size and record that the digest was skipped.

## Sequence

1. Land PR #3.
2. Schema first: the `supplements` block and `schema_version: 2`, with the
   descriptions carrying the design, as was done for `paper_availability`.
3. The second SKILL.md, written against the CLI contract above.
4. Port `supplement_fetch`, then the layout and unpack half of
   `supplement_store`, with their tests.
5. Wire the CLI group; verify against a real corpus including the preprint and
   the 445 MB case.
6. Tag, test from GitHub in the testbed, PR.
