# Plan: supplementary-material retrieval

**Phase 1 of two.** This phase gets the bytes and records honestly what arrived.

## Content annotation is not an aim of this phase

Stated first because it is the constraint everything else follows from, and
because it is easy to drift across by accident.

Nothing here reads what a supplement *says*. No spreadsheet is opened, no
sheet outlined, no prose extracted, no relevance judged, no table
characterised. A retrieved file is an opaque blob with a label on it. If a
question can only be answered by looking inside a data file, it is not this
phase's question.

**What is recorded is what the publisher already told us**: the filename, the
media type, the size, the archive members, and any description the authors or
the publisher wrote. That last one is worth being precise about, because
"description" sounds like annotation and is not: a caption lifted verbatim out
of the article XML is a machine fact, copied, with its source named. It is not
a judgement anybody made about the contents. See "What gets recorded about each
file" below for exactly where a description may come from and what may be done
with it.

Inspecting and annotating what was retrieved is **phase 2**, deliberately
postponed — including what it does and where it lives — and will be its own PR.

For boundary purposes only, phase 2 is expected to be **limited inspection of
contents by a cheap agent, plus choosing what to inspect**. That is recorded
here not to design it but because it constrains one thing about this phase: the
choosing has to be possible from the listing alone, without opening anything.
See "What phase 1 owes phase 2" below. Everything else about phase 2 — what it
looks for, what it writes, where it lives — is open.

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
`tables`/`prose` sections. A retrieved file is an opaque blob with a label.

**Out, permanently:** fetching from arbitrary external repositories. Where a
data-availability statement points at Zenodo, figshare, GEO or Dryad, that
pointer is recorded as a gap with its URL. Scraping unknown hosts is fragile,
and a named pointer is already actionable.

## What gets recorded about each file

Per file, and per archive member: `filename`, `media_type`, `size_bytes`,
`sha256`, where it came from, and a `description` with a `description_source`.

The description is **harvested, never composed**. Three places it may come
from, and the record says which:

| `description_source` | where it comes from |
|---|---|
| `jats_caption` | the `<supplementary-material>` caption in the article XML |
| `bundle_manifest` | a manifest, index or README *inside* the bundle that maps filenames to the authors' own labels |
| `biorxiv_label` | the label the preprint server's supplement page carries |

Two rules keep this on the right side of the line:

- **Verbatim or absent.** A harvested description is copied, not paraphrased,
  not summarised, not merged across sources. Where two sources disagree, keep
  the article XML's and record the other in a note; a blended description
  cannot be checked against anything.
- **A bundle manifest may be read; a data file may not.** Reading a file whose
  job is to describe the bundle is retrieval — it is a listing, the same kind of
  thing as the archive's own member table. Opening a spreadsheet of results to
  see what is in it is annotation, and it is phase 2. The distinction is what
  the file is *for*, and it is testable: a manifest is recognised by name
  (`manifest`, `index`, `README`, `contents`, `file_list`) and by being small.

This is worth the care because a caption is often the best description that
will ever exist for a supplement — publishers write things like "Supplementary
Tables 1–40" or "Source Data Figs. 2 and 4", which no amount of looking at the
bytes would recover. Capturing it now is cheap and it is not annotation. What
it is *for* is a phase-2 question.

## What phase 1 owes phase 2

Phase 2 chooses what to inspect and then inspects a little of it with a cheap
agent. Choosing is the part that reaches back into this phase: **it has to be
possible from the record alone, with nothing opened.** Inspection is the
expensive step, so anything that narrows it before a file is read pays for
itself, and a selection that has to open forty workbooks to find out which one
matters has already lost.

The fields a selection can run on are exactly the ones this phase records
anyway — so this is a constraint that happens to already be satisfied, which is
worth stating rather than discovering later:

| what a selector needs | where it comes from |
|---|---|
| what the authors say a file is | `description` + `description_source` |
| what kind of thing it is | `media_type` |
| whether it is cheap or costly to open | `size_bytes` |
| what is inside an archive, without unpacking it | `members` — names, media types, sizes |
| whether the bytes are even here | `status`, and `deferred` where a fetch was declined on size |

Two obligations follow, and both are cheap now and expensive to retrofit:

- **Record the member table even when nothing is extracted.** A zip's central
  directory gives names, sizes and media types for free, and it is the only
  thing that turns "one opaque 445 MB bundle" into a list a selector can reason
  about. Unpacking is a separate decision from listing.
- **Keep the caption attached to the file, not the paper.** A per-paper blob of
  captions cannot be selected on.

What phase 1 must *not* do for phase 2 is pre-judge. No relevance field, no
content-type guess, no "probably a DEG table" — those are the selection, and
putting a half-made one in a retrieval record would have phase 2 inherit a
verdict nobody stands behind. The upstream schema hangs `relevance` on
`SupplementFile`; this phase deliberately omits it.

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

## Large bundles: ask before downloading, do not cap silently

A 445 MB download is a decision about somebody's disk, time and possibly
tethered connection. Upstream handles it with a default cap, which turns a
question into a silent truncation — the paper ends up recorded as partially
retrieved because of a limit nobody was told about.

So this phase makes it a **pre-flight check with a threshold**:

1. Before fetching a bundle, ask the host for its size — a `HEAD`, or the
   `Content-Length` of a `GET` abandoned after the headers.
2. Under the threshold (proposed default **50 MB**): fetch without comment.
3. Over it: **do not fetch.** Exit 2, print the size, what is in the bundle if
   the listing already says (the video is usually identifiable by media type),
   and the flag that proceeds. Record the attempt as `deferred` — a fourth
   outcome, distinct from `unavailable`, meaning nothing was learnt because
   nobody was asked yet.
4. `--max-bundle-bytes N` raises or lowers the threshold; `--yes-large`
   proceeds for this run; `--skip-large` records the deferral and moves on to
   the next paper without stopping the batch.

Two consequences worth designing for:

- **A batch must not block on a prompt.** Over a 22-paper corpus this has to be
  a non-interactive decision: the default is defer-and-continue, and the
  operator re-runs with a flag for the ones they want. A CLI that waits for a
  keystroke halfway through a corpus is worse than one that caps.
- **`Content-Length` is often absent** on a chunked response. Then the size
  cannot be known in advance, so fall back to streaming with the cap and abort
  on exceeding it — recording `deferred` with a note that the size was not
  declared, not `unavailable`. A host that will not say how big something is
  has told us nothing about whether the file exists.

Where the listing already carries per-file sizes — the article XML sometimes
does — a bundle can be skipped in favour of fetching only the wanted files
publisher-direct, which is both smaller and more precise. Worth doing where the
template exists.

This is also the first thing the *skill* has to exercise judgement about:
reporting "this paper's supplements are 445 MB, most of it one video" and
letting a person decide is the useful behaviour, and quietly fetching 250 MB of
it is not.

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
                                 [--yes-large | --skip-large]
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
- **Whether a large bundle is worth fetching.** The record says how big and, if
  the listing is good enough, what makes it big. Put that in front of the user
  with the flag to proceed rather than deciding for them; and where only one
  table is wanted out of 445 MB, say that fetching it publisher-direct is an
  option.
- **A deferral is not an absence.** A paper whose bundle was skipped on size
  has supplements nobody has fetched yet, and a report that lists it beside a
  paper with none is wrong.
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
- **The size gate gets its own.** Over-threshold defers rather than truncating;
  `deferred` never reads as `unavailable`; a missing `Content-Length` defers
  rather than claiming the file is not there; `--skip-large` keeps a batch
  moving; and a harvested description survives a deferral, because the listing
  is what makes a deferral reportable.
- **Descriptions stay verbatim.** A test that a caption is byte-identical to the
  article XML, and that a bundle manifest never overwrites one.
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
- **Size caps and honesty.** The 445 MB case means a threshold will bite on
  real papers. Every cap and every deferral needs its trace tested, not just
  implemented.
- **The description line gets crossed by accident.** "Read the bundle manifest
  but not the data files" is a rule somebody will overstep while adding a
  publisher, because a manifest and a small results table look alike from the
  outside. The recognition rule — named like an index, and small — should be one
  function with its own tests, not a condition spread across the fetchers.

## Open questions

1. ~~Does the listing record enough for a later focus choice?~~ **Resolved.**
   Phase 2 is limited inspection by a cheap agent plus choosing what to
   inspect, and the inputs a chooser needs are the fields this phase records
   anyway — see "What phase 1 owes phase 2". The two obligations that came out
   of it: record an archive's member table even when nothing is extracted, and
   keep each caption on its file rather than in a per-paper blob.
2. **Does `report` belong per-paper or per-store?** Both are useful; a store-wide
   coverage table is probably what a corpus needs first.
3. **Is a supplement worth a digest if it is never read?** Yes for change
   detection, but hashing a 445 MB video costs real time. Possibly cap hashing
   by size and record that the digest was skipped.
4. **Is 50 MB the right threshold?** It sits above the observed 14–28 MB
   typical case and below the 60 MB PNAS paper, so on the reference corpus it
   would defer two papers out of 22. That feels about right for a default that
   is meant to be noticed rather than endured, but it is a guess until it runs
   on a corpus somebody is waiting for.
5. **Does a deferral need re-probing?** A deferred bundle's size is recorded, so
   a later run could decide without another `HEAD`. Cheap either way; the
   question is whether a stale size is worse than an extra request.

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
