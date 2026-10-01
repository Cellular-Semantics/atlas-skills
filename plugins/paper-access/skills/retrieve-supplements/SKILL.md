---
name: retrieve-supplements
description: Get a paper's supplementary material — the tables, workbooks and documents a publisher attaches rather than printing — and say honestly what arrived. Reads the file list and the publisher's captions out of the article XML, fetches from the publisher's host or Europe PMC's bundle, unpacks archives, and refuses to download half a gigabyte without asking. Use after `paper-access` has fetched the papers, when a question needs the supplementary tables rather than the text.
---

# retrieve-supplements

Supplementary material carries what a paper's text often cannot: the
differential-expression tables, the cluster-to-name mappings, the per-cell
metadata. This gets the files and records what they are. **It does not read
them.**

## This does not look inside anything

No spreadsheet is opened, no sheet outlined, no document extracted, no table
characterised, no relevance judged. A retrieved file is an opaque blob with a
label on it. If a question can only be answered by looking inside a data file,
it is not this skill's question — say so rather than reaching for `Read`, which
on a 400,000-row table wrecks your context for no gain.

What *is* recorded is what the publisher already said: the filename, the media
type, the size, an archive's member list, and any description the authors wrote.
A caption is a machine fact, copied verbatim with its source named — it is not
somebody's judgement about the contents, and it is often the best description
that will ever exist. "Supplementary Tables 1–40" is a real caption, and nothing
recoverable from the bytes would tell you that.

Print the record schema with `paper-access schema` and read the `supplements`
block; it documents its own fields.

## Requirements

Papers first. `retrieve-supplements` reads the article XML that
`paper-access fetch` wrote, because the supplementary filenames and the
publisher's captions live there and nowhere else. A paper this skill has no
record for is a paper to fetch, not a paper with no supplements.

## The mechanical half

```bash
alias paper-access='uvx --from "git+https://github.com/Cellular-Semantics/atlas-skills@pkg-paper-access--v0.3.0#subdirectory=packages/paper-access" paper-access'

# What files does this paper have? Free: reads the XML already on disk.
paper-access supplements list --store <store> --id <id>

# Fetch them. Declines a very large download unless told otherwise.
paper-access supplements fetch --store <store> --id <id> [--retry]
#   --yes-large          proceed with a download over the threshold
#   --skip-large         record the deferral and exit 0, so a batch keeps going
#   --large-bytes N      move the bundle threshold (default 250 MB)
#   --include-media      fetch figures and video too; off at any size
#   --file-timeout N     wall-clock seconds per file (default 120)
#   --paper-timeout N    wall-clock seconds per paper (default 600)
#   --no-bundle          skip the Europe PMC bundle route

# A corpus, not one paper at a time. Every command below takes these.
paper-access supplements fetch --store <store> --all --concurrency 4
paper-access supplements fetch --store <store> --input ids.txt
paper-access supplements list  --store <store> --all

# Expand archives, recording the member table either way.
paper-access supplements unpack --store <store> --id <id>

# Take in files somebody found by hand.
paper-access supplements adopt --store <store> --id <id> --incoming <dir>

# One paper's supplements, with any inconsistency flagged.
paper-access supplements show --store <store> --id <id>

# Coverage across the store.
paper-access supplements report --store <store> [--json]
```

`fetch` runs `list` for you if nothing has been listed yet, and is cheap to
re-run: a file already here is not re-fetched, and one recorded as missing or
deferred is left alone until `--retry`.

**Use `--all` or `--input` for a corpus.** A sweep reports per paper with a
summary naming what errored and what needs a decision, and its exit code is
about the sweep rather than one paper: 0 if everything was attempted and
nothing waits on you, 2 if something does, 1 if a paper errored. Hand-rolling
the loop in a shell is how the timeouts go missing.

## How the files are found, and why in that order

**The article XML first**, because it is free and it is the only place the
publisher's captions exist. On a real corpus it accounts for most papers.

**Then a data-availability statement**, in whatever text is on disk. This finds
pointers rather than files — an accession at GEO, a Zenodo DOI. Those are
recorded as gaps with their addresses and **deliberately not fetched**: crawling
arbitrary hosts is fragile, and an accession is already something a person can
act on. Report them; do not try to download them.

**Then the snippet index**, but only for a paper with no local text at all.
There is nothing to grep for such a paper, so a paper-scoped search for
data-availability wording is the only way to see where its material lives.

**Then the preprint server**, for a preprint, which has no PMC record and so is
invisible to everything above.

Bytes come from the publisher's own host where the URL shape is known — one
122 KB workbook instead of everything around it — then from Europe PMC's
bundle, then from the preprint server, then from a person.

## What is yours to judge

### A listing with no bytes is a result

The most important thing this skill reports. "Eleven supplements and we could
not get any of them" and "this paper appears to have none" are completely
different findings, and a report that blurs them is worse than no report. `list`
succeeding and `fetch` failing is a normal, informative outcome.

### What is wanted is a question of kind, not size

Figures and video are **skipped at any size**, because size is a poor proxy for
whether a file is wanted: on one paper a 226 MB video was fetched while 46 small
tables were refused, which is wrong on both counts. `--include-media` overrides.
The byte limit that remains is a backstop at 200 MB per file, applied the same
way on every route.

A skipped file is `skipped`, not `missing`, and gets no gap. The difference is
whose decision it was, and nobody needs asking about a file we did not want.

### Whether a large download is worth it

A bundle over the threshold is **deferred**, not fetched. Two things to know
when you report one:

- **A bundle cannot be partly transferred.** A zip's member table is at the end
  of the file, so no member can be read without fetching the whole archive.
  Media-type policy governs what is *extracted* and what the per-file routes
  fetch; it cannot make a bundle smaller. If you are tempted to say "we only
  need the one table so fetch just that", it is only true where the publisher's
  template is known.
- **Europe PMC declares no size for a bundle** — not by `HEAD`, `GET` or a
  `Range` request. So its size is genuinely unknown until it has been
  transferred, and where a transfer was abandoned the record carries
  `bytes_transferred`, which is a lower bound, and *not* `size_bytes`. Do not
  quote the one as the other. On the publisher routes a size is declared and the
  decision is made before anything moves.

**`deferred` is not `unavailable`.** Nothing was learnt about whether a deferred
file could have been got — nobody has asked yet. Reporting it as missing is a
straightforward falsehood, and so is leaving it out of a count.

### Whether a file is what it claims

Bytes arriving is not the same as a file arriving. A publisher served 5.5 MB
claiming to be a workbook that no zip reader can open; Europe PMC's bundle for
one paper carries a truncated copy of a workbook the publisher serves whole.
Both are checked and discarded rather than stored with a digest, because a
corrupt file recorded as present looks authoritative and fails much later. Where
`retrieval.note` says something was discarded, that file is worth asking for by
hand.

### Why a description is missing

`caption_source` says which: `jats` where the article XML captioned them,
`none_in_jats` where it carried none — an author-manuscript deposit never does —
and `no_jats` where there was no article XML to read. A bundle of uncaptioned
files is a property of the source, not a failure to look, and a caption is often
the best description a supplement will ever have. Say which case it is rather
than leaving a blank column.

### Which dropped file is which supplement

`adopt` matches on filename. Anything it cannot match is taken in under its own
name and reported as unmatched rather than filed as something it is not — the
same discipline as adopting a paper. If an unmatched file is obviously
`Supplementary Table 3` under a different name, say so and ask; do not assume.

## Reporting

Give the counts by status — present, listed, deferred, missing — and then the
gaps, each with what would fix it. Two failures to avoid:

- **Rounding off.** "Supplements retrieved" for a paper where four of nineteen
  are missing is wrong. Say four.
- **Treating "not looked at" as "none".** A paper nobody has run `list` on has
  unknown supplements, and `report` distinguishes that from a paper with none.
  Keep the distinction when you summarise.
- **Counting a skip as a loss.** `skipped` files were not wanted. Report them
  separately from `missing` or not at all, never as a shortfall.
- **Quoting a timeout as an absence.** A `timeout` outcome means a host was too
  slow, which says nothing about whether the file exists. It is worth retrying;
  `unavailable` is not.

For a store-wide sweep, `report` gives you the table. Name the papers that need
a size decision separately from the ones that need a person to find a file: they
need different actions.

## What comes next, and is not here

Working out which of these files answers a question — which sheet holds the DEG
table, whether a document's methods section bears on cell typing — is a separate
job against a separate artefact, and it is deliberately not part of this skill.
There is no relevance field on a retrieval record, so that "not yet judged" can
never be read as "judged irrelevant".
