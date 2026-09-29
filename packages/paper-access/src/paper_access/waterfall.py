"""The waterfall, and the two ways a paper arrives outside it.

Order: JATS XML, then the ASTA index probe, then an open-access PDF, then
asking a person. The reasoning is in the package docstring; what matters here
is one structural consequence. **The probe is not a rung in the ordinary
sense.** It runs for every paper whatever happened above it, because nothing
else reports snippet coverage and the band is worth having on every record. It
becomes the *route* only where no rung produced bytes and the band is ``full``.

So the loop below is: try the byte-producing rungs in order, probe regardless,
then decide what the route was.
"""

from __future__ import annotations

import logging
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

import httpx

from . import asta as asta_module
from . import pdftext, sources, store
from .errors import PaperAccessError
from .ids import DOI_RE, Identifier, looks_exact, normalise_doi, now, parse_id
from .record import Attempt, Availability, LocalSource

logger = logging.getLogger(__name__)

#: Rungs that can put bytes on disk, in the order they are tried.
RUNGS = (
    ("europepmc", sources.rung_europepmc),
    ("preprint_server", sources.rung_preprint_server),
    ("unpaywall", sources.rung_unpaywall),
)

#: Suffixes that could hold a paper. A supplementary spreadsheet in the same
#: directory is not a candidate, and neither is a figure.
PAPER_SUFFIXES = (".pdf", ".xml", ".jats", ".nxml")


# ----------------------------------------------------------------------
# Resolving input to identifiers
# ----------------------------------------------------------------------


def resolve(
    raw: str, *, client: httpx.Client | None = None, limit: int = 5
) -> dict[str, Any]:
    """Turn one line of input into either an identifier or a list of candidates.

    An exact identifier is taken as given and costs nothing. Anything else is
    searched, and comes back as candidates for a person to confirm — never as
    an answer. Two papers by the same group in the same year on the same tissue
    is the normal case in this literature.

    Returns:
        ``{"input", "status", ...}``. Status ``confirmed`` carries ``kind`` and
        ``value``; status ``candidates`` carries a ``candidates`` list; status
        ``unresolved`` carries a ``reason``.
    """
    text = raw.strip()
    if not text:
        return {"input": raw, "status": "unresolved", "reason": "blank line"}

    if looks_exact(text):
        kind, value = parse_id(text)
        return {"input": raw, "status": "confirmed", "kind": kind, "value": value}

    owned = client is None
    active = client or httpx.Client(timeout=60, follow_redirects=True)
    try:
        found = sources.search_candidates(text, active, limit=limit)
    finally:
        if owned:
            active.close()

    if not found:
        return {
            "input": raw,
            "status": "unresolved",
            "reason": "no Europe PMC match; give a DOI, a PMID or a PMCID",
        }
    return {"input": raw, "status": "candidates", "candidates": found}


# ----------------------------------------------------------------------
# The waterfall
# ----------------------------------------------------------------------


def settled(record: Availability) -> bool:
    """Whether an earlier failure to retrieve this paper is worth believing.

    The negative cache exists so a paper nobody can get is not re-requested on
    every pass. It should only hold where the rungs actually answered. A rung
    that broke, or could not run because something was not installed, has
    established nothing — and if that counted as settled, an afternoon's outage
    would leave a retrievable paper permanently marked unreachable.
    """
    byte_rungs = [a for a in record.attempts if a.route != "asta_probe"]
    return bool(byte_rungs) and all(a.outcome == "unavailable" for a in byte_rungs)


def _reusable(store_root: str | Path, identifier: str) -> Availability | None:
    """An existing record whose stored bytes are still there and unchanged."""
    record = store.read(store_root, identifier)
    if record is None or record.local_source is None:
        return None
    if not store.intact(store_root, record):
        return None
    return record


def _gap_for(store_root: str | Path, record: Availability) -> dict[str, str]:
    """What to ask a person for, in terms they can act on.

    Where a resolver named an open-access landing page it could not download
    from, that page is the best place to send someone: it is a free copy, and
    the only reason it is not here is that the host will not serve it to a
    script.
    """
    kind, value = record.primary_id
    named = f'"{record.title}" ({value})' if record.title else value
    reasons = "; ".join(
        f"{a.route} {a.outcome}" + (f" — {a.note}" if a.note else "")
        for a in record.attempts
    )
    pages = [loc["url"] for loc in record.oa_candidates if loc.get("url")]
    if pages:
        where = f"an open-access copy is at {pages[0]}"
    elif kind == "doi":
        where = f"the paper is at https://doi.org/{value}"
    else:
        where = f"look the paper up by {kind.upper()} {value}"
    return {
        "what": named,
        "reason": f"no route produced the text: {reasons}",
        "action": (
            f"{where} — download the PDF or article XML and take it in with "
            f"`paper-access adopt --store {store_root} --id {value} --file <path>`"
        ),
    }


def _attach(store_root: str | Path, record: Availability, fetched: sources.Fetched) -> None:
    """Write a rung's bytes into the store and describe them on the record."""
    target = store.store_bytes(store_root, record, fetched.kind, fetched.body)
    local = LocalSource(
        kind=fetched.kind,
        path=f"{store.SOURCE_DIR}/{target.name}",
        sha256=store.digest(fetched.body),
        bytes=len(fetched.body),
        url=fetched.url,
    )
    if fetched.kind == "pdf":
        try:
            text, quality = pdftext.extract(target)
        except PaperAccessError as exc:
            # The PDF is here and the text is not. Recorded rather than raised:
            # the bytes are still worth keeping and a person can re-extract.
            record.attempts.append(
                Attempt("unpaywall", "failed", f"PDF stored but not readable: {exc}", now())
            )
        else:
            store.store_text(store_root, record, text)
            local.text_file = f"{store.SOURCE_DIR}/{store.TEXT_NAME}"
            local.text_quality = quality
    record.local_source = local
    record.fetched_at = now()


def fetch(
    identifier: str,
    store_root: str | Path,
    *,
    retry: bool = False,
    allow_pdf: bool = True,
    probe_asta: bool = True,
    contact: str | None = None,
    asta_key: str | None = None,
    timeout: float = 60.0,
) -> Availability:
    """Walk the waterfall for one paper and write its record.

    Args:
        identifier: An exact DOI, PMID or PMCID. Anything vaguer has to go
            through :func:`resolve` and be confirmed by a person first.
        store_root: Directory the papers live under.
        retry: Try again for a paper an earlier run could not get. Without
            this, a paper recorded as unreachable is left alone — which is the
            point of recording it.
        allow_pdf: Whether to accept a PDF. Off keeps a corpus to tagged
            article XML, at the cost of the papers only available as PDFs.
        probe_asta: Whether to measure snippet coverage. On by default and
            rarely worth turning off: it is one call and it is the only way to
            know.
        contact: Address for the open-access resolver.
        asta_key: ASTA API key. Falls back to ``ASTA_API_KEY``.
        timeout: Per-request timeout, in seconds.

    Returns:
        The record, already written. Route ``none`` is a normal outcome and
        carries a gap saying what to ask a person for.
    """
    kind, value = parse_id(identifier)

    reused = _reusable(store_root, identifier)
    if reused is not None:
        logger.info("%s: already here via %s", value, reused.route)
        return reused

    previous = store.read(store_root, identifier)
    if previous is not None and previous.route == "none" and not retry and settled(previous):
        logger.info("%s: recorded as unreachable by every route; --retry to try again", value)
        return previous

    record = Availability(input=identifier, attempted_at=now())
    record.ids[kind] = Identifier.given(value)
    if previous is not None:
        for other_kind, found in previous.ids.items():
            store.add_id(record, other_kind, found)
        if previous.metadata is not None:
            record.metadata = previous.metadata
        if previous.notes:
            record.notes = previous.notes

    address = sources.contact_email(contact)
    headers = {"User-Agent": f"paper-access ({address or 'no contact address'})"}
    with httpx.Client(timeout=timeout, headers=headers, follow_redirects=True) as client:
        ctx = sources.Context(client=client, contact=address)

        fetched: sources.Fetched | None = None
        for name, rung in RUNGS:
            fetched = rung(record, ctx)
            if fetched is None:
                continue
            if fetched.kind == "pdf" and not allow_pdf:
                record.attempts[-1] = Attempt(
                    name,
                    "skipped",
                    f"a PDF was available at {fetched.url} but PDFs were declined",
                    now(),
                )
                fetched = None
                continue
            break

        if probe_asta:
            record.asta = asta_module.probe(
                _asta_paper_id(record), client=client, key=asta_key
            )
            # The probe never produces bytes, so 'ok' here means "the index
            # holds enough of this paper to serve it" rather than "this is
            # where the file came from". The cross-checks know to exclude
            # asta_probe when they ask which rung produced the paper.
            if record.asta.band == "skipped":
                outcome = "skipped"
            elif record.asta.servable:
                outcome = "ok"
            else:
                outcome = "unavailable"
            record.attempts.append(
                Attempt("asta_probe", outcome, record.asta.reason, record.asta.probed_at)
            )

    if fetched is not None:
        record.route = next(
            a.route for a in reversed(record.attempts)
            if a.outcome == "ok" and a.route != "asta_probe"
        )
        _attach(store_root, record, fetched)
    elif record.asta is not None and record.asta.servable:
        # Nothing on disk, but the index holds the paper. A real route, with
        # no bytes and no figure legends.
        record.route = "asta"
    else:
        record.route = "none"
        record.gap = _gap_for(store_root, record)

    store.write(store_root, record)
    return record


def _asta_paper_id(record: Availability) -> str:
    """How ASTA wants this paper named.

    DOIs go bare; the numeric kinds need their prefix or the service reads them
    as a Semantic Scholar id.
    """
    doi = record.ids.get("doi")
    if doi is not None:
        return doi.value
    pmid = record.ids.get("pmid")
    if pmid is not None:
        return f"PMID:{pmid.value}"
    pmcid = record.ids.get("pmcid")
    if pmcid is not None:
        return f"PMCID:{pmcid.value}"
    raise PaperAccessError("no identifier to probe with")


# ----------------------------------------------------------------------
# Taking in a file a person supplied
# ----------------------------------------------------------------------


def _kind_of(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return "pdf"
    if suffix in (".xml", ".jats", ".nxml"):
        return "jats"
    raise PaperAccessError(
        f"{path.name} is neither a PDF nor article XML; a paper has to be one or the other"
    )


def adopt(identifier: str, store_root: str | Path, file_path: str | Path) -> Availability:
    """Take a file a person supplied and record it as this paper's source.

    A supplied file is a route like any other, and for some papers it is the
    only route there is. What it is not is unchecked: a PDF that is really an
    HTML error page, or XML that is really a saved landing page, would
    otherwise be read as the paper.
    """
    kind, value = parse_id(identifier)
    source = Path(file_path)
    if not source.is_file():
        raise PaperAccessError(f"no such file: {source}")
    file_kind = _kind_of(source)
    body = source.read_bytes()

    if file_kind == "pdf" and not body.startswith(b"%PDF"):
        raise PaperAccessError(f"{source.name} has a .pdf name but does not start with %PDF")
    if file_kind == "jats":
        head = body[:4000].decode("utf-8", errors="replace")
        if "<article" not in head:
            raise PaperAccessError(
                f"{source.name} has an XML name but no <article> element in its opening — "
                "a saved landing page rather than article XML?"
            )

    record = Availability(input=identifier, route="manual", attempted_at=now())
    record.ids[kind] = Identifier.given(value)
    previous = store.read(store_root, identifier)
    if previous is not None:
        for other_kind, found in previous.ids.items():
            store.add_id(record, other_kind, found)
        record.metadata = previous.metadata
        record.asta = previous.asta
        record.notes = previous.notes
    record.attempts.append(
        Attempt("manual", "ok", f"supplied by hand, copied from {source}", now())
    )
    _attach(store_root, record, sources.Fetched(kind=file_kind, body=body))
    store.write(store_root, record)
    return record


def note(identifier: str, store_root: str | Path, text: str) -> Availability:
    """Set the one free-text field a record has.

    Everything else on a record is written from an API response. This is where
    something a person knows and the CLI cannot — that a PDF is the accepted
    manuscript, that a DOI resolves to a correction — goes, and it is
    deliberately the only such place: a note cannot be mistaken for an
    identifier or for publisher metadata.
    """
    record = store.read(store_root, identifier)
    if record is None:
        raise PaperAccessError(f"no record for {identifier} in {store_root}")
    record.notes = text
    store.write(store_root, record)
    return record


# ----------------------------------------------------------------------
# Reading a bag of supplied files
# ----------------------------------------------------------------------


def _xml_identity(path: Path) -> tuple[str | None, str | None]:
    """The DOI and title an article XML declares, from its opening."""
    try:
        head = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None, None
    doi = None
    for match in DOI_RE.finditer(head[:200_000]):
        try:
            doi = normalise_doi(match.group(0))
        except PaperAccessError:
            continue
        break
    title = None
    try:
        root = ET.fromstring(head.replace("<!DOCTYPE", "<!--DOCTYPE", 1))
    except ET.ParseError:
        return doi, None
    for element in root.iter():
        if element.tag.split("}", 1)[-1] == "article-title":
            title = " ".join(" ".join(element.itertext()).split()).strip()
            break
    return doi, title


def _pdf_identity(path: Path) -> tuple[str | None, str | None]:
    """The DOI and a title guess from a PDF's first page.

    Only the first page is read. Working out which paper a PDF is by reading
    all of it would cost as much as reading the paper.
    """
    try:
        import pymupdf
    except ImportError:
        try:
            import fitz as pymupdf  # type: ignore[no-redef]
        except ImportError:
            return None, None
    try:
        with pymupdf.open(path) as document:
            if not len(document):
                return None, None
            text = document[0].get_text()
    except Exception:
        return None, None

    doi = None
    for match in DOI_RE.finditer(text):
        try:
            doi = normalise_doi(match.group(0))
        except PaperAccessError:
            continue
        break
    lines = [line.strip() for line in text.splitlines() if len(line.strip()) > 25]
    return doi, lines[0] if lines else None


def candidates(inputs_dir: str | Path) -> list[dict[str, Any]]:
    """Every file under a directory that could be a paper, described enough to place.

    A drop zone is a flat bag with papers, supplements and figures in it, and
    nobody is asked to name files a particular way. So this says what each
    candidate is — the DOI it declares, the title it opens with, how big it is
    — and leaves matching files to papers to a reader, which is a judgement and
    not a pattern match. The absence of a DOI is the strongest signal on offer:
    a published paper almost always carries its own in the front matter, and a
    supplement does not.
    """
    root = Path(inputs_dir)
    if not root.is_dir():
        raise PaperAccessError(f"no such directory: {root}")

    out: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in PAPER_SUFFIXES:
            continue
        kind = "pdf" if path.suffix.lower() == ".pdf" else "jats"
        doi, title = _pdf_identity(path) if kind == "pdf" else _xml_identity(path)
        entry: dict[str, Any] = {
            "path": str(path),
            "relative_path": str(path.relative_to(root)),
            "kind": kind,
            "n_bytes": path.stat().st_size,
        }
        if doi:
            entry["doi"] = doi
        if title:
            entry["title"] = title[:300]
        if kind == "pdf" and doi is None and title is None:
            entry["note"] = (
                "could not be read; PyMuPDF is missing (the [text-access] extra) "
                "or the PDF has no text on page 1"
            )
        out.append(entry)
    return out


# ----------------------------------------------------------------------
# Auditing a store
# ----------------------------------------------------------------------


def verify(
    store_root: str | Path, *, client: httpx.Client | None = None
) -> list[dict[str, Any]]:
    """Re-resolve every record's identifiers and check the titles still agree.

    Catches drift, and catches anything that got into a store before the write
    was locked down. One lookup per paper.
    """
    owned = client is None
    active = client or httpx.Client(timeout=60, follow_redirects=True)
    out: list[dict[str, Any]] = []
    try:
        for record in store.read_all(store_root):
            kind, value = record.primary_id
            entry: dict[str, Any] = {"id": value, "kind": kind}
            try:
                result = sources.europepmc_record(kind, value, active)
            except Exception as exc:
                entry["status"] = "unchecked"
                entry["note"] = f"lookup failed: {exc}"
                out.append(entry)
                continue
            if result is None:
                entry["status"] = "unknown"
                entry["note"] = "Europe PMC has no record of this identifier"
                out.append(entry)
                continue
            found = str(result.get("title") or "").rstrip(".")
            entry["title_on_record"] = record.title
            entry["title_now"] = found
            if not record.title:
                entry["status"] = "no_title"
            elif _titles_agree(record.title, found):
                entry["status"] = "ok"
            else:
                entry["status"] = "mismatch"
                entry["note"] = "the identifier resolves to a different paper than recorded"
            out.append(entry)
    finally:
        if owned:
            active.close()
    return out


def _titles_agree(left: str, right: str) -> bool:
    """Whether two titles are the same paper, allowing for publisher noise."""
    def flatten(value: str) -> str:
        return "".join(ch for ch in value.lower() if ch.isalnum())

    a, b = flatten(left), flatten(right)
    if not a or not b:
        return False
    return a == b or a.startswith(b[:60]) or b.startswith(a[:60])


def report(store_root: str | Path) -> list[dict[str, Any]]:
    """One row per paper: identifier, route, what is on disk, ASTA band."""
    rows: list[dict[str, Any]] = []
    for record in store.read_all(store_root):
        try:
            kind, value = record.primary_id
        except PaperAccessError:
            kind, value = "unconfirmed", record.input
        row: dict[str, Any] = {
            "id": value,
            "id_kind": kind,
            "route": record.route,
            "title": record.title,
        }
        if record.local_source:
            row["kind"] = record.local_source.kind
            row["bytes"] = record.local_source.bytes
            if record.local_source.text_quality:
                row["text_chars"] = record.local_source.text_quality.get("n_chars")
                row["text_readable"] = pdftext.looks_readable(
                    record.local_source.text_quality
                )
        if record.asta:
            row["asta_band"] = record.asta.band
        if record.gap:
            row["gap"] = record.gap.get("action")
        rows.append(row)
    return rows
