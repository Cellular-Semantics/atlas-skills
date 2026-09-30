"""The rungs that find supplementary files, and the rungs that fetch them.

Unlike the paper waterfall, where the rungs are alternatives, the first group
here produces a **listing** and the second produces **bytes**. A listing is
worth having on its own: it is the difference between "eleven supplements
nobody could get" and "this paper appears to have none".

Ordering and coverage come from probing a 22-paper corpus across Springer
Nature, Cell Press, AAAS, JCI, Wiley, Oxford, PNAS and a preprint. The article
XML served 14 of 22.
"""

from __future__ import annotations

import logging
import re
import tempfile
import urllib.parse
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, BinaryIO

import httpx

from .errors import PaperAccessError
from .ids import now
from .supplements import (
    SupplementAttempt,
    SupplementFile,
    SupplementRetrieval,
    media_type,
)

logger = logging.getLogger(__name__)

EUROPEPMC_BASE = "https://www.ebi.ac.uk/europepmc/webservices/rest"
BIORXIV_CONTENT = "https://www.biorxiv.org/content"

#: Spool a streamed bundle to disk past this, so a 197 MB download costs disk
#: rather than RAM and the size gate can stay generous.
SPOOL_TO_DISK_BYTES = 32 * 1024 * 1024

XLINK = "{http://www.w3.org/1999/xlink}href"


def _text_of(element: ET.Element) -> str:
    return " ".join(" ".join(element.itertext()).split()).strip()


# ----------------------------------------------------------------------
# Listing: the article XML
# ----------------------------------------------------------------------


def listing_from_jats(jats_path: str | Path) -> list[SupplementFile]:
    """The supplementary files an article's XML declares.

    The cheapest source of the file list, and the only place the publisher's
    labels and captions live. A caption like "Supplementary Tables 1-40" often
    describes the contents better than anything recoverable from the bytes,
    which is why it is worth reading before a single file is opened — and why
    doing so is not annotation.
    """
    path = Path(jats_path)
    try:
        root = ET.parse(path).getroot()
    except (OSError, ET.ParseError) as exc:
        raise PaperAccessError(f"cannot parse {path}: {exc}") from exc

    out: list[SupplementFile] = []
    seen: set[str] = set()
    for element in root.iter():
        if not element.tag.endswith("supplementary-material"):
            continue
        href = element.get(XLINK) or element.get("href")
        if not href:
            # Some publishers hang the filename on a nested <media>.
            for child in element.iter():
                if child.tag.endswith("media"):
                    href = child.get(XLINK) or child.get("href")
                    if href:
                        break
        if not href or href in seen:
            continue
        seen.add(href)

        label = caption = ""
        for child in element.iter():
            tag = child.tag.rsplit("}", 1)[-1]
            if tag == "label" and not label:
                label = _text_of(child)
            elif tag == "caption" and not caption:
                caption = _text_of(child)

        name = Path(href).name
        entry = SupplementFile(
            file_id=name,
            filename=name,
            status="listed",
            media_type=media_type(name),
            label=label or None,
            retrieval=SupplementRetrieval(route="jats_listing"),
        )
        if caption:
            entry.describe(caption, "jats_caption")
        out.append(entry)
    return out


# ----------------------------------------------------------------------
# Listing: the preprint server
# ----------------------------------------------------------------------

BIORXIV_ENTRY_MARKER = "supplementary-material-expansion"
BIORXIV_LINK = re.compile(r'href="([^"]+/embed/[^"?]+)[^"]*"')
BIORXIV_LABEL = re.compile(r'supplementary-material-label"[^>]*>([^<]+)<')


def parse_biorxiv_page(page: str) -> list[dict[str, str]]:
    """Files and labels from a preprint's supplementary-material page.

    The page is both the listing and the source of bytes, so for a preprint
    this one rung stands in for the article XML and the publisher host at once.
    """
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for chunk in page.split(BIORXIV_ENTRY_MARKER)[1:]:
        link = BIORXIV_LINK.search(chunk)
        if not link:
            continue
        href = link.group(1)
        if href in seen:
            continue
        seen.add(href)
        url = href if href.startswith("http") else f"https://www.biorxiv.org{href}"
        entry = {"url": url, "file_id": Path(urllib.parse.urlparse(url).path).name}
        label = BIORXIV_LABEL.search(chunk)
        if label:
            entry["label"] = " ".join(label.group(1).split())
        out.append(entry)
    return out


def biorxiv_get(url: str) -> tuple[bytes | None, str]:
    """Fetch from the preprint server, which is behind Cloudflare."""
    try:
        from curl_cffi import requests as impersonating
    except ImportError:
        return None, "getting past Cloudflare needs curl_cffi (the [text-access] extra)"
    try:
        response = impersonating.get(url, impersonate="chrome120", timeout=120)
    except Exception as exc:
        return None, f"{type(exc).__name__}: {exc}"
    if response.status_code != 200:
        return None, f"HTTP {response.status_code}"
    return response.content, "ok"


def listing_from_biorxiv(doi: str, version: int = 1) -> tuple[list[SupplementFile], str]:
    """A preprint's supplements, from the page that lists them."""
    url = f"{BIORXIV_CONTENT}/{doi}v{version}.supplementary-material"
    body, note = biorxiv_get(url)
    if body is None:
        return [], note
    entries = parse_biorxiv_page(body.decode("utf-8", errors="replace"))
    out: list[SupplementFile] = []
    for entry in entries:
        name = entry["file_id"]
        found = SupplementFile(
            file_id=name,
            filename=name,
            status="listed",
            media_type=media_type(name),
            label=entry.get("label"),
            retrieval=SupplementRetrieval(route="biorxiv", url=entry["url"]),
        )
        if entry.get("label"):
            found.describe(entry["label"], "biorxiv_label")
        out.append(found)
    return out, "ok" if out else "the page lists no supplementary files"


# ----------------------------------------------------------------------
# Bytes: the Europe PMC bundle
# ----------------------------------------------------------------------


@dataclass
class BundleResult:
    """A downloaded bundle, a deferral, or why there is not one.

    ``outcome`` is what goes on the record, and the distinctions matter:
    ``deferred`` means nobody has agreed to the download, ``failed`` means the
    transport broke and is worth retrying, ``unavailable`` means the host
    answered and this article has no open bundle.
    """

    archive: zipfile.ZipFile | None
    note: str
    outcome: str = "unavailable"
    size_bytes: int | None = None
    buffer: BinaryIO | None = None

    def close(self) -> None:
        if self.archive is not None:
            self.archive.close()
        if self.buffer is not None:
            self.buffer.close()


def fetch_bundle(
    client: httpx.Client,
    pmcid: str,
    *,
    large_bytes: int,
    max_bytes: int,
    allow_large: bool,
) -> BundleResult:
    """Stream the article's supplement bundle, deciding on size from the headers.

    Europe PMC serves every supplement for an article as one zip with no way to
    select files, so the size question has to be answered before the body is
    read. It cannot be answered by ``HEAD``: **the endpoint does not respond to
    HEAD at all** — it hangs rather than refusing — while ``GET`` returns the
    zip perfectly well. So the request is a streamed ``GET`` whose headers are
    read and whose body is abandoned unread when the answer is no.

    Europe PMC declares no length at all — the bundle is chunked — so most of
    the time the size is not knowable in advance. Refusing on that basis would
    disable the route for every paper, so an undeclared size means the download
    proceeds against the threshold and is abandoned the moment it passes it.
    The cost of finding out is bounded by the threshold; the benefit is that the
    768 KB case, which is most of them, simply works.

    Three failures here look like success and must not:

    * **HTTP 200 with an empty body** — nothing at all for an article whose full
      text is not open.
    * **HTTP 200 with a short non-zip body** — the same case, differently
      served. Either, recorded naively, makes the paper look as though it has no
      supplementary material.
    * **A transport failure** — which establishes nothing about the article and
      so must be ``failed`` rather than ``unavailable``, or an afternoon's
      outage leaves a retrievable bundle marked unreachable.
    """
    url = f"{EUROPEPMC_BASE}/{pmcid}/supplementaryFiles"
    buffer = tempfile.SpooledTemporaryFile(max_size=SPOOL_TO_DISK_BYTES)  # noqa: SIM115
    try:
        with client.stream("GET", url) as response:
            if response.status_code == 404:
                buffer.close()
                return BundleResult(
                    None, "no supplementary bundle for this article", "unavailable"
                )
            if response.status_code != 200:
                buffer.close()
                return BundleResult(
                    None, f"bundle returned HTTP {response.status_code}", "failed"
                )

            raw = response.headers.get("content-length")
            declared = int(raw) if raw and raw.isdigit() else None
            # Europe PMC streams the bundle chunked and declares no length, so
            # an undeclared size is the normal case rather than an evasion.
            # Deferring on it would block the route for every paper; instead
            # the download runs against the threshold and is abandoned if it
            # turns out to be the big one. At most `large_bytes` is wasted.
            over_threshold = declared is not None and declared > large_bytes
            if not allow_large and over_threshold:
                buffer.close()
                return BundleResult(
                    None,
                    f"the bundle is {declared / 1e6:.0f} MB, over the "
                    f"{large_bytes / 1e6:.0f} MB threshold; not downloaded "
                    "without being asked for",
                    "deferred",
                    declared,
                )

            cap = max_bytes if allow_large else large_bytes
            for chunk in response.iter_bytes(1 << 20):
                buffer.write(chunk)
                if buffer.tell() > cap:
                    size = buffer.tell()
                    buffer.close()
                    return BundleResult(
                        None,
                        f"the bundle passed the {cap}-byte limit while downloading "
                        f"(at {size} bytes); abandoned",
                        "deferred",
                        size,
                    )
    except httpx.HTTPError as exc:
        buffer.close()
        return BundleResult(None, f"{type(exc).__name__}: {exc}", "failed")

    size = buffer.tell()
    if size == 0:
        buffer.close()
        return BundleResult(None, "bundle is empty (HTTP 200, zero bytes)", "unavailable", 0)
    buffer.seek(0)
    if not zipfile.is_zipfile(buffer):
        buffer.close()
        return BundleResult(
            None,
            f"bundle is not a zip ({size} bytes) — Europe PMC has no open "
            "supplementary files for this article",
            "unavailable",
            size,
        )
    buffer.seek(0)
    return BundleResult(zipfile.ZipFile(buffer), "ok", "ok", size, buffer)


# ----------------------------------------------------------------------
# Bytes: the publisher's own host
# ----------------------------------------------------------------------


def springer_url(doi: str, filename: str) -> str | None:
    """Springer Nature's static host, which serves ESM files individually.

    Worth having even though the bundle needs no templates: Springer articles
    are the bulk of most corpora, and this fetches one 122 KB workbook where
    the bundle would fetch everything around it.
    """
    if not doi.startswith("10.1038/"):
        return None
    quoted = urllib.parse.quote(f"art:{doi}", safe="")
    return f"https://static-content.springer.com/esm/{quoted}/MediaObjects/{filename}"


#: DOI prefix -> URL builder. Add a publisher when a corpus needs one; the
#: bundle route covers most cases without any of this. An absent template is a
#: recorded skip, never a claim that the file does not exist.
PUBLISHER_URL_BUILDERS = {"10.1038": springer_url}


def publisher_direct_url(doi: str, filename: str) -> str | None:
    """URL for one supplement on its publisher's host, where we know the shape."""
    builder = PUBLISHER_URL_BUILDERS.get(doi.split("/")[0])
    return builder(doi, filename) if builder else None


def fetch_one_file(client: httpx.Client, url: str, dest: Path, cap: int) -> tuple[bool, str]:
    """Download one file, refusing to keep going past ``cap``."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    try:
        with client.stream("GET", url, follow_redirects=True) as response:
            if response.status_code != 200:
                return False, f"HTTP {response.status_code}"
            with dest.open("wb") as handle:
                for chunk in response.iter_bytes(1 << 20):
                    written += len(chunk)
                    if written > cap:
                        handle.close()
                        dest.unlink(missing_ok=True)
                        return False, f"exceeds the {cap}-byte limit; abandoned"
                    handle.write(chunk)
    except httpx.HTTPError as exc:
        dest.unlink(missing_ok=True)
        return False, f"{type(exc).__name__}: {exc}"
    return True, "ok"


# ----------------------------------------------------------------------
# Integrity
# ----------------------------------------------------------------------

#: Formats whose first bytes let us check a payload is what it claims. xlsx and
#: docx are zip containers; a PDF starts with %PDF.
ZIP_CONTAINER_MEDIA = {"xlsx", "docx", "zip"}


def verify_payload(path: Path, media: str) -> tuple[bool, str]:
    """Check retrieved bytes are structurally the format they claim.

    A route can hand back a file that is the wrong size and unopenable, and
    Europe PMC does: its bundle for one paper carries an 18.5 MB copy of a
    workbook the publisher serves at 35.7 MB, truncated so no zip reader can
    open it. Extracted faithfully and recorded with a digest, that looks
    authoritative and only fails much later.

    Cheap enough for every file — it reads a header, or a zip's central
    directory, never the payload.
    """
    try:
        if media in ZIP_CONTAINER_MEDIA:
            if not zipfile.is_zipfile(path):
                return False, f"claims {media} but is not a zip container"
            with zipfile.ZipFile(path) as archive:
                bad = archive.testzip()
            if bad is not None:
                return False, f"claims {media} but member {bad} is corrupt"
            return True, "ok"
        if media == "pdf":
            with path.open("rb") as handle:
                if handle.read(5) != b"%PDF-":
                    return False, "claims pdf but does not start with %PDF-"
            return True, "ok"
    except (OSError, zipfile.BadZipFile) as exc:
        return False, f"unreadable: {exc}"
    return True, "not checked"


def attempt(route: str, outcome: str, note: str | None = None) -> SupplementAttempt:
    return SupplementAttempt(route=route, outcome=outcome, note=note, at=now())


def pmcid_of(record: Any) -> str | None:
    """The PMCID on an availability record, if it carries one."""
    found = record.ids.get("pmcid")
    return found.value if found is not None else None
