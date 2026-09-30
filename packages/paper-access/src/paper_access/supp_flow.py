"""Walking the supplement waterfall, and the size decision in the middle of it.

Two halves. :func:`list_supplements` finds out what files a paper has, from the
article XML on disk, from a data-availability statement, or from the preprint
server. :func:`fetch_supplements` gets the bytes, and declines to get very large
ones without being told to.

The size decision is the part worth reading. Upstream caps the download, which
turns a question about somebody's disk and time into a truncation nobody was
told about: the paper ends up recorded as partly retrieved because of a limit
that was never surfaced. Here a bundle over the threshold is **deferred** — not
fetched, recorded with its size, and reported with the flag that would proceed.
Deferred is a distinct outcome from unavailable, and nothing may collapse the
two: one means nobody has asked yet, the other means we asked and could not.

A batch must not block on a prompt either. Over a corpus the default is
defer-and-continue, so twenty-one papers still get done while the
four-hundred-megabyte one waits for a decision.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import httpx

from . import store, supp_sources
from .ids import now
from .record import Availability
from .supplements import (
    FIGURE_MEDIA,
    TABULAR_MEDIA,
    ArchiveMember,
    SupplementFile,
    SupplementRetrieval,
    Supplements,
    find_pointers,
    looks_like_manifest,
    media_type,
    pointer_gap,
)

logger = logging.getLogger(__name__)

SUPPLEMENTS_DIR = "supplements"

#: Over this, a bundle is not downloaded without being asked for. Above the
#: observed 14-28 MB typical case and below the 60 MB outlier, so on a real
#: corpus it defers the few papers worth a decision rather than all of them.
DEFAULT_LARGE_BYTES = 50 * 1024 * 1024

#: Hard ceiling on a single download once it has been agreed to, so a host that
#: streams forever cannot fill a disk.
DEFAULT_MAX_BYTES = 2 * 1024 * 1024 * 1024

#: Per-member extraction caps. A results table legitimately runs to hundreds of
#: megabytes, and a 445 MB video does not.
MEMBER_CAP_BYTES = 80 * 1024 * 1024
TABULAR_MEMBER_CAP_BYTES = 512 * 1024 * 1024

#: Above this, a digest costs real time for no benefit a reader will notice.
#: Skipping is recorded, never silent.
HASH_MAX_BYTES = 256 * 1024 * 1024


def supplements_dir(store_root: str | Path, record: Availability) -> Path:
    kind, value = record.primary_id
    return store.paper_dir(store_root, kind, value) / SUPPLEMENTS_DIR  # type: ignore[arg-type]


# ----------------------------------------------------------------------
# Listing
# ----------------------------------------------------------------------


def list_supplements(
    record: Availability,
    store_root: str | Path,
    *,
    client: httpx.Client | None = None,
    asta_key: str | None = None,
) -> Supplements:
    """Find out what supplementary files this paper has.

    Tries the article XML first because it is free and carries the publisher's
    captions; then, for a paper with no XML, looks for a data-availability
    statement in whatever text there is; then asks the snippet index, but only
    where there is no local text at all to read.
    """
    found = record.supplements or Supplements()
    found.listed_at = now()

    source = store.source_path(store_root, record)
    kind = record.local_source.kind if record.local_source else None

    # 1. The article XML: filenames and captions, already on disk.
    if source is not None and kind == "jats" and source.is_file():
        try:
            listed = supp_sources.listing_from_jats(source)
        except Exception as exc:
            found.listing_sources.append(
                supp_sources.attempt("jats_listing", "failed", str(exc))
            )
        else:
            for entry in listed:
                found.add(entry)
            found.listing_sources.append(
                supp_sources.attempt(
                    "jats_listing",
                    "ok" if listed else "unavailable",
                    f"{len(listed)} file(s) declared in the article XML"
                    if listed
                    else "the article XML declares no supplementary material",
                )
            )
    else:
        found.listing_sources.append(
            supp_sources.attempt(
                "jats_listing", "skipped", "no article XML on disk for this paper"
            )
        )

    # 2. A data-availability statement in the text we have.
    text = _local_text(store_root, record)
    if text:
        pointers = find_pointers(text)
        _record_pointers(found, pointers)
        found.listing_sources.append(
            supp_sources.attempt(
                "local_text_scan",
                "ok" if pointers else "unavailable",
                f"{len(pointers)} repository pointer(s) named in the text"
                if pointers
                else "no repository pointer in the text",
            )
        )
    else:
        found.listing_sources.append(
            supp_sources.attempt(
                "local_text_scan", "skipped", "no local text to read for this paper"
            )
        )
        # 3. Only where there is nothing on disk: ask the index. For a paper
        #    served from ASTA there is no other way to see a data-availability
        #    statement at all.
        pointers, note, outcome = _asta_pointers(record, client=client, key=asta_key)
        _record_pointers(found, pointers)
        found.listing_sources.append(supp_sources.attempt("asta_scan", outcome, note))

    # 4. A preprint lists its own supplements; rungs 1-3 are blind to them.
    doi = record.ids.get("doi")
    untouched = not [f for f in found.files if f.status != "listed" or f.members]
    if doi is not None and untouched and _is_preprint(record):
        listed, note = supp_sources.listing_from_biorxiv(doi.value)
        for entry in listed:
            found.add(entry)
        found.listing_sources.append(
            supp_sources.attempt("biorxiv_page", "ok" if listed else "unavailable", note)
        )

    return found


def _local_text(store_root: str | Path, record: Availability) -> str:
    """Whatever text of this paper is on disk, for scanning only."""
    if record.local_source is None:
        return ""
    base = store.source_path(store_root, record)
    if base is None:
        return ""
    directory = base.parent.parent
    for relative in (record.local_source.text_file, record.local_source.path):
        if not relative:
            continue
        path = directory / relative
        if path.is_file() and path.suffix.lower() in (".txt", ".xml"):
            try:
                return path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
    return ""


def _asta_pointers(
    record: Availability, *, client: httpx.Client | None, key: str | None
) -> tuple[list[dict[str, str]], str, str]:
    from . import asta as asta_module

    resolved = asta_module.api_key(key)
    if not resolved:
        return [], f"no {asta_module.API_KEY_ENV}, so the index was not asked", "skipped"
    paper_id = _asta_paper_id(record)
    if paper_id is None:
        return [], "no identifier the index accepts", "skipped"

    owned = client is None
    active = client or httpx.Client(timeout=180, follow_redirects=True)
    try:
        rows = asta_module.search_snippets(
            paper_id,
            client=active,
            key=resolved,
            query="data availability accession supplementary material deposited",
            limit=20,
        )
    except Exception as exc:
        return [], f"the index could not be asked: {exc}", "failed"
    finally:
        if owned:
            active.close()

    text = "\n".join((row.get("snippet") or {}).get("text") or "" for row in rows)
    pointers = find_pointers(text)
    return (
        pointers,
        f"{len(pointers)} repository pointer(s) in {len(rows)} indexed snippet(s)"
        if pointers
        else f"no repository pointer in {len(rows)} indexed snippet(s)",
        "ok" if pointers else "unavailable",
    )


def _asta_paper_id(record: Availability) -> str | None:
    for kind, prefix in (("doi", ""), ("pmid", "PMID:"), ("pmcid", "PMCID:")):
        found = record.ids.get(kind)
        if found is not None:
            return f"{prefix}{found.value}"
    return None


def _is_preprint(record: Availability) -> bool:
    if record.route == "preprint_server":
        return True
    doi = record.ids.get("doi")
    return bool(doi and doi.value.startswith(("10.1101/", "10.21203/")))


def _record_pointers(found: Supplements, pointers: list[dict[str, str]]) -> None:
    """A repository pointer is a gap with an address, never a file to fetch."""
    known = {g.get("what") for g in found.gaps}
    for pointer in pointers:
        gap = pointer_gap(pointer)
        if gap["what"] not in known:
            found.gaps.append(gap)
            known.add(gap["what"])


# ----------------------------------------------------------------------
# Bytes
# ----------------------------------------------------------------------


def fetch_supplements(
    record: Availability,
    store_root: str | Path,
    *,
    retry: bool = False,
    use_bundle: bool = True,
    large_bytes: int = DEFAULT_LARGE_BYTES,
    max_bytes: int = DEFAULT_MAX_BYTES,
    allow_large: bool = False,
    skip_large: bool = False,
    client: httpx.Client | None = None,
) -> Supplements:
    """Fetch what the listing named, deferring anything too big to fetch quietly.

    Args:
        allow_large: Proceed with a download over ``large_bytes``.
        skip_large: Record the deferral and move on without stopping a batch.
            Differs from ``allow_large=False`` only in what the caller does
            afterwards; both leave the same record.
    """
    found = record.supplements or Supplements()
    found.attempted_at = now()
    directory = supplements_dir(store_root, record) / "files"
    owned = client is None
    active = client or httpx.Client(timeout=180, follow_redirects=True)

    try:
        wanted = [f for f in found.files if _should_attempt(f, retry)]
        if not wanted:
            found.attempts.append(
                supp_sources.attempt(
                    "europepmc_bundle",
                    "skipped",
                    "nothing to fetch: every listed file is already here or settled",
                )
            )
            return found

        # Publisher-direct first where we know the template: it fetches one
        # 122 KB workbook where the bundle fetches everything around it.
        doi = record.ids.get("doi")
        if doi is not None:
            _try_publisher_direct(found, wanted, doi.value, directory, active, max_bytes)

        wanted = [f for f in found.files if _should_attempt(f, retry)]
        if wanted and use_bundle:
            _try_bundle(
                found, record, directory, active,
                large_bytes=large_bytes, max_bytes=max_bytes,
                allow_large=allow_large, skip_large=skip_large,
            )

        wanted = [f for f in found.files if _should_attempt(f, retry)]
        if wanted:
            _try_biorxiv(found, wanted, directory, max_bytes)

        for entry in found.files:
            # Only a file no byte rung ever touched is missing. One a rung saw
            # and deliberately passed over — a figure image — stays `listed`:
            # it is known to exist and its bytes were not fetched, which is
            # what `listed` means. Sweeping it into `missing` would put a gap
            # on the record asking somebody to go and find a file nobody
            # wanted.
            if entry.status == "listed" and entry.retrieval.route in ("jats_listing", "none"):
                entry.status = "missing"
                entry.retrieval.attempted_at = now()
                _gap_for_missing(found, entry, record)
    finally:
        if owned:
            active.close()

    if any(f.status == "present" for f in found.files):
        found.fetched_at = now()
    return found


def _should_attempt(entry: SupplementFile, retry: bool) -> bool:
    if entry.status == "present":
        return False
    if entry.status == "missing" and not retry:
        return False
    return not (entry.status == "deferred" and not retry)


def _try_publisher_direct(
    found: Supplements,
    wanted: list[SupplementFile],
    doi: str,
    directory: Path,
    client: httpx.Client,
    max_bytes: int,
) -> None:
    urls = {e.file_id: supp_sources.publisher_direct_url(doi, e.file_id) for e in wanted}
    if not any(urls.values()):
        found.attempts.append(
            supp_sources.attempt(
                "publisher_direct",
                "skipped",
                f"no URL template for the publisher of {doi}; the bundle covers "
                "most cases without one",
            )
        )
        return

    got = 0
    for entry in wanted:
        url = urls.get(entry.file_id)
        if not url:
            continue
        target = directory / entry.file_id
        ok, note = supp_sources.fetch_one_file(client, url, target, max_bytes)
        if not ok:
            entry.retrieval.attempted_at = now()
            entry.retrieval.note = note
            continue
        _accept(entry, target, directory, "publisher_direct", url)
        # A file that failed its integrity check was discarded, so it did not
        # arrive however healthy the download looked.
        if entry.status == "present":
            got += 1
    found.attempts.append(
        supp_sources.attempt(
            "publisher_direct",
            "ok" if got else "unavailable",
            f"{got} of {len(wanted)} file(s) from the publisher's host",
        )
    )


def _try_bundle(
    found: Supplements,
    record: Availability,
    directory: Path,
    client: httpx.Client,
    *,
    large_bytes: int,
    max_bytes: int,
    allow_large: bool,
    skip_large: bool,
) -> None:
    pmcid = supp_sources.pmcid_of(record)
    if not pmcid:
        found.attempts.append(
            supp_sources.attempt(
                "europepmc_bundle", "skipped", "this paper has no PMCID to fetch a bundle for"
            )
        )
        return

    result = supp_sources.fetch_bundle(
        client, pmcid,
        large_bytes=large_bytes, max_bytes=max_bytes, allow_large=allow_large,
    )
    try:
        if result.outcome == "deferred":
            _defer_bundle(found, pmcid, result.size_bytes, result.note, skip_large)
            return
        if result.archive is None:
            found.attempts.append(
                supp_sources.attempt("europepmc_bundle", result.outcome, result.note)
            )
            return
        got = _take_from_bundle(found, result, directory)
        found.attempts.append(
            supp_sources.attempt(
                "europepmc_bundle",
                "ok" if got else "unavailable",
                f"{got} file(s) from a {result.size_bytes}-byte bundle",
            )
        )
    finally:
        result.close()


def _defer_bundle(
    found: Supplements,
    pmcid: str,
    size: int | None,
    note: str,
    skip_large: bool,
) -> None:
    """Record a bundle nobody has agreed to download yet."""
    why = f"{pmcid}: {note}"
    what = (
        f"the supplementary bundle for {pmcid} ({size / 1e6:.0f} MB)"
        if size is not None
        else f"the supplementary bundle for {pmcid}, size unknown"
    )
    found.attempts.append(supp_sources.attempt("europepmc_bundle", "deferred", why))
    for entry in found.files:
        if entry.status in ("listed", "missing"):
            entry.status = "deferred"
            entry.retrieval.attempted_at = now()
            entry.retrieval.note = why
            found.gaps.append({
                "what": entry.label or entry.file_id,
                "reason": why,
                "action": (
                    "re-run with --yes-large to fetch it, --max-bundle-bytes to raise "
                    "the threshold, or fetch the one file you want from the publisher"
                ),
                "file_id": entry.file_id,
            })
    if not found.files:
        found.gaps.append({
            "what": what,
            "reason": why,
            "action": "re-run with --yes-large, or --max-bundle-bytes to raise the threshold",
        })
    if skip_large:
        logger.info("%s: bundle deferred on size; continuing", pmcid)


def _take_from_bundle(
    found: Supplements, result: supp_sources.BundleResult, directory: Path
) -> int:
    """Extract the wanted members, and record the member table either way."""
    archive = result.archive
    assert archive is not None
    got = 0

    # A bundle with nothing listed for it is itself the file: record it as one
    # entry whose members are the bundle's contents.
    listed_ids = {e.file_id for e in found.files}
    # Manifests are harvested after the loop: a manifest describes its
    # siblings, and during the loop half of them are not on the record yet.
    manifests: list[tuple[Path, str]] = []
    for info in archive.infolist():
        if info.is_dir():
            continue
        name = Path(info.filename).name
        entry = found.by_id(name)
        if entry is None and name not in listed_ids:
            entry = found.add(
                SupplementFile(
                    file_id=name,
                    filename=name,
                    status="listed",
                    media_type=media_type(name),
                    retrieval=SupplementRetrieval(route="europepmc_bundle"),
                )
            )
        if entry is None:
            continue
        if entry.status == "present":
            continue

        kind = media_type(name)
        if kind in FIGURE_MEDIA:
            # Listed, not missing: the bundle had it and we chose to leave it.
            # Recording the route is what tells the missing-sweep that this
            # file was seen rather than never reached.
            entry.status = "listed"
            entry.size_bytes = info.file_size
            entry.media_type = kind
            entry.retrieval = SupplementRetrieval(
                route="europepmc_bundle",
                note="a figure image; deliberately not extracted",
            )
            continue
        cap = TABULAR_MEMBER_CAP_BYTES if kind in TABULAR_MEDIA else MEMBER_CAP_BYTES
        if info.file_size > cap:
            entry.status = "deferred"
            entry.size_bytes = info.file_size
            entry.retrieval.attempted_at = now()
            entry.retrieval.note = (
                f"{info.file_size} bytes, over the {cap}-byte per-file limit; "
                "left in the bundle"
            )
            found.gaps.append({
                "what": entry.label or entry.file_id,
                "reason": entry.retrieval.note,
                "action": "raise the limit, or extract it from the bundle by hand",
                "file_id": entry.file_id,
            })
            continue

        target = directory / name
        target.parent.mkdir(parents=True, exist_ok=True)
        with archive.open(info) as source, target.open("wb") as handle:
            while chunk := source.read(1 << 20):
                handle.write(chunk)
        _accept(entry, target, directory, "europepmc_bundle")
        if entry.status == "present":
            got += 1
            if looks_like_manifest(name, entry.size_bytes):
                manifests.append((target, name))

    for path, name in manifests:
        _harvest_manifest(found, path, name)
    return got


def _try_biorxiv(
    found: Supplements, wanted: list[SupplementFile], directory: Path, max_bytes: int
) -> None:
    candidates = [e for e in wanted if e.retrieval.route == "biorxiv" and e.retrieval.url]
    if not candidates:
        found.attempts.append(
            supp_sources.attempt(
                "biorxiv", "skipped", "no preprint-server URLs listed for this paper"
            )
        )
        return
    got = 0
    for entry in candidates:
        body, note = supp_sources.biorxiv_get(str(entry.retrieval.url))
        if body is None:
            entry.retrieval.attempted_at = now()
            entry.retrieval.note = note
            continue
        if len(body) > max_bytes:
            entry.status = "deferred"
            entry.size_bytes = len(body)
            entry.retrieval.note = f"{len(body)} bytes, over the {max_bytes}-byte limit"
            found.gaps.append({
                "what": entry.label or entry.file_id,
                "reason": entry.retrieval.note,
                "action": "raise the limit with --max-bundle-bytes",
                "file_id": entry.file_id,
            })
            continue
        target = directory / entry.file_id
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(body)
        _accept(entry, target, directory, "biorxiv", str(entry.retrieval.url))
        got += 1
    found.attempts.append(
        supp_sources.attempt(
            "biorxiv",
            "ok" if got else "unavailable",
            f"{got} of {len(candidates)} file(s) from the preprint server",
        )
    )


def _accept(
    entry: SupplementFile,
    target: Path,
    directory: Path,
    route: str,
    url: str | None = None,
) -> None:
    """Record a file that arrived, having checked it is what it claims."""
    size = target.stat().st_size
    kind = entry.media_type or media_type(entry.file_id)
    ok, note = supp_sources.verify_payload(target, kind)
    if not ok:
        target.unlink(missing_ok=True)
        entry.status = "missing"
        entry.retrieval = SupplementRetrieval(
            route=route, url=url, attempted_at=now(),
            note=f"retrieved {size} bytes and discarded them: {note}",
        )
        return

    entry.status = "present"
    entry.size_bytes = size
    entry.media_type = kind
    entry.path = f"{SUPPLEMENTS_DIR}/files/{target.name}"
    entry.retrieval = SupplementRetrieval(route=route, url=url, retrieved_at=now())
    if note != "ok":
        entry.retrieval.note = note
    if size <= HASH_MAX_BYTES:
        entry.sha256 = store.digest(target.read_bytes())
    else:
        entry.retrieval.note = (
            (entry.retrieval.note + "; ") if entry.retrieval.note else ""
        ) + f"digest skipped: {size} bytes is over the {HASH_MAX_BYTES}-byte hashing limit"


def _harvest_manifest(found: Supplements, target: Path, name: str) -> None:
    """Take labels from a file whose job is to describe the bundle.

    The one place this phase reads inside a file, and only for files that
    :func:`looks_like_manifest` accepts — named like an index, and small. A
    results table called ``index.csv`` is data and is not read.
    """
    if not looks_like_manifest(name, target.stat().st_size):
        return
    try:
        text = target.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or len(stripped) > 400:
            continue
        for entry in found.files:
            if entry.file_id == name or entry.file_id not in stripped:
                continue
            remainder = stripped.replace(entry.file_id, " ").strip(" \t,;:-|\"'")
            if remainder:
                entry.describe(remainder, "bundle_manifest")


def _gap_for_missing(found: Supplements, entry: SupplementFile, record: Availability) -> None:
    _, value = record.primary_id
    reasons = entry.retrieval.note or "no route produced it"
    found.gaps.append({
        "what": entry.label or entry.file_id,
        "reason": reasons,
        "action": (
            f"find it on the publisher's page for {value}, put it anywhere, and take "
            f"it in with `paper-access supplements adopt --id {value} --incoming <dir>`"
        ),
        "file_id": entry.file_id,
    })


# ----------------------------------------------------------------------
# Unpacking, and taking in what a person found
# ----------------------------------------------------------------------


def unpack(
    record: Availability,
    store_root: str | Path,
    *,
    member_cap: int = MEMBER_CAP_BYTES,
    tabular_cap: int = TABULAR_MEMBER_CAP_BYTES,
) -> Supplements:
    """Expand stored archives, recording the member table either way.

    Listing a member and extracting it are separate decisions. The member table
    comes from the zip's own central directory, so it costs nothing and is
    recorded even when nothing is extracted — it is what turns one opaque
    bundle into a list worth reasoning about.
    """
    import zipfile

    found = record.supplements or Supplements()
    base = supplements_dir(store_root, record)
    for entry in found.files:
        if entry.status != "present" or entry.media_type != "zip" or not entry.path:
            continue
        archive_path = base.parent / entry.path
        if not archive_path.is_file():
            continue
        out = base / "unpacked" / entry.file_id
        members: list[ArchiveMember] = []
        try:
            with zipfile.ZipFile(archive_path) as archive:
                for info in archive.infolist():
                    if info.is_dir():
                        continue
                    kind = media_type(info.filename)
                    member = ArchiveMember(
                        member_path=info.filename,
                        media_type=kind,
                        size_bytes=info.file_size,
                        extracted=False,
                    )
                    cap = tabular_cap if kind in TABULAR_MEDIA else member_cap
                    if kind in FIGURE_MEDIA:
                        member.note = "a figure image; not extracted"
                    elif info.file_size > cap:
                        member.note = (
                            f"{info.file_size} bytes, over the {cap}-byte limit; "
                            "left in the archive"
                        )
                        found.gaps.append({
                            "what": f"{entry.file_id}/{info.filename}",
                            "reason": member.note,
                            "action": "raise the limit, or extract it by hand",
                            "file_id": entry.file_id,
                        })
                    else:
                        target = out / Path(info.filename).name
                        target.parent.mkdir(parents=True, exist_ok=True)
                        with archive.open(info) as source, target.open("wb") as handle:
                            while chunk := source.read(1 << 20):
                                handle.write(chunk)
                        member.extracted = True
                        member.path = (
                            f"{SUPPLEMENTS_DIR}/unpacked/{entry.file_id}/{target.name}"
                        )
                    members.append(member)
        except zipfile.BadZipFile as exc:
            entry.retrieval.note = f"stored but not a readable zip: {exc}"
            continue
        entry.members = members
    return found


def adopt(
    record: Availability,
    store_root: str | Path,
    incoming: str | Path,
) -> tuple[Supplements, list[dict[str, Any]]]:
    """Take files a person dropped into the store.

    Matching a dropped filename to a listed supplement is the caller's
    judgement, not this function's: anything whose name matches a listed
    ``file_id`` is taken in as that file, and everything else is taken in under
    its own name and reported, so nothing is quietly filed as something it is
    not.
    """
    found = record.supplements or Supplements()
    source_dir = Path(incoming)
    if not source_dir.is_dir():
        raise store.PaperAccessError(f"no such directory: {source_dir}")

    directory = supplements_dir(store_root, record) / "files"
    unmatched: list[dict[str, Any]] = []
    for path in sorted(source_dir.rglob("*")):
        if not path.is_file():
            continue
        entry = found.by_id(path.name)
        target = directory / path.name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(path.read_bytes())
        if entry is None:
            entry = found.add(
                SupplementFile(
                    file_id=path.name,
                    filename=path.name,
                    status="listed",
                    media_type=media_type(path.name),
                )
            )
            unmatched.append({"file_id": path.name, "n_bytes": path.stat().st_size})
        _accept(entry, target, directory, "manual")
    found.attempts.append(
        supp_sources.attempt(
            "manual",
            "ok" if not unmatched or found.files else "unavailable",
            f"{len(list(source_dir.rglob('*')))} path(s) offered, "
            f"{len(unmatched)} not named in any listing",
        )
    )
    return found, unmatched
