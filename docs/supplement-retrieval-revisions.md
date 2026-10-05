# Revisions after testing: supplement retrieval

Follow-up to [`supplement-retrieval-plan.md`](supplement-retrieval-plan.md),
from a real corpus sweep of ~30 papers. Three of the reported diagnoses are
corrected below, with evidence; the rest go in as reported.

**Status: all implemented**, including batch mode, which the plan put in a
second PR. It moved here because the next round of testing is a corpus sweep,
and a hand-rolled shell loop would muddy the results with the loop's own bugs
rather than the fixes'. Package and plugin 0.3.0, record schema 3.

One further bug the implementation found, not in the report: **`.gif` was absent
from the media table entirely**, so nothing skipped it — and an
author-manuscript bundle is mostly figure GIFs. The zero-byte GIF that stranded
`sridhar_2020_retina` was therefore being extracted in the first place. Added
`gif`, `bmp`, `webp`, `mkv`, `wmv`, `m4v`, with a test that every figure and
video extension resolves to a type the policy skips — the failure mode is an
extension nobody listed, so the test enumerates rather than spot-checks.

## Corrections to the diagnosis

### The blocker is a truthiness bug, not a missing write

Reported as "`size_bytes` is enforced as an invariant on read but not set on
write for bundle-extracted files. Either set it from the extracted bytes or
don't mark the file present."

It **is** set — to `0`. `nihms-1610745-f0008.gif` is a zero-byte member of an
author-manuscript bundle, and the cross-check reads

```python
if not entry.get("size_bytes"):
    problems.append(f"{file_id}: status is 'present' but size_bytes is missing")
```

so `0` fails a check meant to catch absence. Reproduced:

```
size_bytes present in dict: True
cross_check: ["f0008.gif: status is 'present' but size_bytes is missing"]
```

This matters because the suggested remedy would not have fixed it. The fix is
`is None`. Swept the rest of both cross-checks: this is the **only** site with
the mistake today, so the guard that is worth more than the fix is a test that
every numeric field tolerates `0` — `size_bytes`, `bytes`, `n_chars`,
`n_segments`, `n_snippets` — because the next one will be written the same way.

Two further consequences the report implies but does not state:

- **A validation failure on write must not be able to strand a paper.** The
  record was unwritable, so every subsequent run — including `--retry` — died
  at the same point, and `--no-bundle` was the only escape. A paper that cannot
  be written is a paper whose whole corpus sweep is blocked by one zero-byte
  GIF. `write` should fall back to recording the paper as failed-to-write with
  the problems in a note, rather than raising through the batch.
- **A zero-byte supplement is a real thing a publisher serves.** It should be
  `present` with `size_bytes: 0` and a note saying the file is empty, which is
  information, rather than being hidden by an invariant.

### "Decide before transferring" is not achievable for the bundle

Reported as "HEAD for Content-Length first, then decide."

Europe PMC does not give a length by any means. Measured against
`PMC7360023/supplementaryFiles`:

| request | result |
|---|---|
| `HEAD` | 200 in 0.9 s, **no `Content-Length`** |
| `GET` | 200, chunked, **no `Content-Length`** |
| `GET` with `Range: bytes=0-0` | 200 (not 206), no `Content-Range` |

(An earlier 30-second `HEAD` timeout, which is why the code stopped sending
one, was transient. `HEAD` works; it just answers nothing useful.)

Nor is there a per-file route to fall back on:

| candidate | result |
|---|---|
| `europepmc.org/articles/<PMCID>/bin/<file>` | 403 — blocked to scripts |
| `ncbi.nlm.nih.gov/pmc/articles/<PMCID>/bin/<file>` | 404 for this article |
| `…/supplementaryFiles?fileName=<file>` | 200, and returns the whole zip |

So for a PMC-only paper the bundle is the only route and **its size cannot be
known before transferring it**. The requirement behind the report is still
right and is met differently:

- **Stop calling the abandonment point a size.** `53477376` is bytes
  transferred before giving up, and recording it as the bundle's size is a
  false statement. A separate `bytes_transferred` field, with `size_bytes`
  absent and the note saying the size is unknown.
- **Raise the threshold so the realistic case is not abandoned.** 53 MB was
  abandoned under a 50 MB limit for a paper of 46 small tables. The observed
  distribution is 14–28 MB typical, 60 MB for a 34-file paper, 445 MB for one
  with a video. A 50 MB threshold cuts straight through the middle of normal.
- **Send `HEAD` anyway**, because some hosts do answer it, and decide from it
  where there is an answer. It costs ~1 s and it is the only way the publisher
  routes get a decision before transferring.

### A video inside a zip cannot be avoided

Point 3 — skip video by media type at any size — is right and fixes the
observed symptom, but not by the route the report implies.

The 226 MB video was fetched **publisher-direct**, one file at a time, where a
media-type policy applies cleanly and would have skipped it. The 46 refused
tables were in a **bundle**, where it would not have helped: a zip's central
directory is at the end of the file, so no member can be read without
transferring the whole archive. Media-type policy governs *extraction* and the
*per-file* routes; it cannot govern bundle transfer.

Worth stating in the skill text, because it is exactly the kind of thing a
reader will assume works both ways.

## Accepted as reported

- **Deferred records carry no size.** True, and on the bundle route the honest
  version is `bytes_transferred` plus "size not declared by the host". On the
  per-file routes a declared length is available and must be recorded.
- **Prefer per-file over the bundle where sizes are known.** Right instinct,
  and narrower in reach than it looks: it needs a publisher URL template, and
  only Springer has one. Worth adding templates for the publishers a corpus
  actually hits, and worth preferring per-file wherever a template exists — but
  it cannot be the general answer, because PMC has no per-file route at all.
- **Media-type policy, applied identically on every route.** Currently the caps
  differ by route — `MEMBER_CAP_BYTES` 80 MB, `TABULAR_MEMBER_CAP_BYTES`
  512 MB, `DEFAULT_MAX_BYTES` 2 GB — which is incoherent. One policy: skip
  video and images by default at any size, keep one numeric backstop at 200 MB
  per file, applied the same way everywhere.
- **No real timeout.** Diagnosis confirmed and the mechanism is worth naming:
  `httpx.Client(timeout=180)` is **per-operation**, not total, so a host that
  trickles one chunk every 170 s never trips it. 17 minutes with zero bytes is
  consistent with that. Needs a wall-clock deadline we enforce, per file and
  per paper, with a recorded `timeout` outcome.
- **No batch mode.** `paper-access fetch` already takes repeatable `--id` and
  `--input`; the `supplements` subcommands take a single `--id`. That
  inconsistency is the bug. Add `--input`/`--all` and a concurrency flag.
- **No migration path.** Accepted, and my original reasoning was wrong. I made
  v2 refuse v1 so that an absent `supplements` block could not read as "this
  paper has none" — but a v1 record genuinely *has* not been looked at, which
  is exactly what an absent block means in v2. The upgrade is lossless and
  should be automatic: tolerate older versions on read, upgrade on write.
- **Bad accession.** Confirmed, and it is the 600-character clip inside
  `find_pointers` cutting an accession in half. Reproduced: a block of
  `E-MTAB-10000…10059` yields `E-MTAB-100`, truncated from `E-MTAB-10039`,
  alongside 40 valid ones. Clip on a word boundary, and match accessions before
  any clipping.
- **Raw XML in gap text.** Confirmed. `_local_text` reads `paper.jats.xml` as
  plain text, so the scanned "sentence" is markup. Strip tags before scanning,
  and prefer recovered text where it exists.
- **No captions on the bundle route.** Confirmed and worth recording as a
  reason rather than a blank: author-manuscript XML carries no
  `<supplementary-material>` captions, so the absence is a property of the
  source, not a failure to look.

## Things the report did not raise

- **`listed` is now overloaded.** It means both "known to exist, no route has
  got it yet" and "a route had it and we chose to skip it" — and after the
  media-type policy lands, the second will be the common case. A reader cannot
  tell them apart, and `report` counts them together. Needs a distinct
  `skipped` status.
- **Exit code 2 and batch mode conflict.** `supplements fetch` exits 2 when
  anything deferred, which is right for one paper and wrong for a sweep, where
  the useful exit code is about whether the sweep ran. Batch mode needs its own
  convention: 0 if every paper was attempted, 2 only if something needs a
  decision, and a summary that names which.
- **Hashing a file we then discard.** `_accept` verifies, then hashes. For a
  226 MB file that is a wasted pass over the bytes if the media-type policy is
  going to skip it anyway. Order: policy, verify, hash.

## Plan

Two PRs. The blockers go into the open one, because shipping a bug that can
strand a corpus is worse than a wider diff.

### Into PR #4 (`feature/supplement-retrieval`)

1. **Numeric invariants.** `is None` at the one site that has it, plus a
   parametrised test that every numeric field in both records tolerates `0`.
2. **A write failure cannot strand a paper.** `store.write` keeps raising for
   programmer error, but the supplement flow catches it, records the problems
   in the record's note, and leaves the paper re-runnable.
3. **Zero-byte supplements are present with a note.**
4. **Media-type policy, one place, every route.** `SKIP_MEDIA` = video and
   images, skipped by default at any size with `--include-media` to override.
   One numeric backstop, `MAX_FILE_BYTES` 200 MB, applied identically. Remove
   the three divergent caps. New `skipped` status.
5. **Sizes told honestly.** `HEAD` first on every route that will answer;
   `size_bytes` only ever a declared or measured size; `bytes_transferred` for
   an abandoned transfer; "size not declared" in the note where that is the
   truth. Bundle threshold to 250 MB, so the 60 MB case is not abandoned and
   the 445 MB one still is.
6. **Per-file preferred where a template exists**, and the skill text corrected
   to say that a bundle cannot be partially transferred.
7. **Wall-clock deadlines.** `--file-timeout` (default 120 s) and
   `--paper-timeout` (default 600 s), enforced by us against a monotonic clock,
   with a `timeout` outcome in `attempts`.
8. **Schema tolerance.** Read versions 1 and 2, upgrade on write, and a
   `paper-access migrate --store` for doing it in bulk without fetching.
   Version 3 for the field changes above.
9. **Accession extraction.** Match before clipping; clip on a word boundary;
   strip markup before scanning. Tests for the truncation case and the XML case
   with the exact strings observed.
10. **Caption absence recorded** with its reason on the author-manuscript path.

### A second PR: batch mode

`--input ids.txt` / `--all` plus `--concurrency` on `supplements list`, `fetch`
and `unpack`, a per-paper summary, and exit codes that mean something for a
sweep. Separate because it changes the CLI surface for both skills and deserves
its own review, and because it is the one item here that is a feature rather
than a correction.

### Verification

Unit tests for every item, as before. Then a real sweep over the same corpus
before merging: the test that matters is that 30 papers go through without a
hand-rolled loop, without a hang, and without a paper stranding the run.
