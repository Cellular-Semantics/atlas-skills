"""The rungs: Europe PMC, the preprint servers, an open-access resolver.

Each rung takes the paper it is looking for and the record it appends its
attempt to, and returns bytes or nothing. Every rung records what it did,
including the rungs that ran and found nothing — that is what stops a paper
nobody can get being re-requested on every later pass, and it is also what
separates "this paper is not on Europe PMC" from "Europe PMC was down".
"""

from __future__ import annotations

import logging
import os
import re
import subprocess
import urllib.parse
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import httpx

from .ids import Identifier, normalise_doi, normalise_pmcid, normalise_pmid, now
from .record import Attempt, Availability, Metadata
from .store import add_id

logger = logging.getLogger(__name__)

EUROPEPMC_BASE = "https://www.ebi.ac.uk/europepmc/webservices/rest"
IDCONV_URL = "https://www.ncbi.nlm.nih.gov/pmc/utils/idconv/v1.0/"
PREPRINT_DETAILS = "https://api.biorxiv.org/details"
UNPAYWALL_BASE = "https://api.unpaywall.org/v2"

#: Preprint servers sharing the bioRxiv details API. Both are tried: a DOI one
#: does not host costs a single cheap lookup, and medRxiv holds a good deal of
#: the clinical single-cell literature.
PREPRINT_SERVERS = ("biorxiv", "medrxiv")

#: Open-access resolvers require a contact address on every request. Sending a
#: placeholder would be rude and is grounds for being blocked, so the rung
#: reports having no address rather than inventing one.
CONTACT_ENV = "PAPER_ACCESS_CONTACT_EMAIL"


@dataclass
class Context:
    """What every rung is given: a shared client and a contact address."""

    client: httpx.Client
    contact: str | None = None


@dataclass
class Fetched:
    """Bytes a rung produced, and what it knows about them."""

    kind: str
    body: bytes
    url: str | None = None


def contact_email(explicit: str | None = None) -> str | None:
    """A contact address for a resolver that requires one.

    An explicit argument, then the environment, then the checkout's git
    identity — so it works without setup for someone in their own clone and is
    overridable for anyone else.
    """
    if explicit:
        return explicit
    from_env = os.getenv(CONTACT_ENV)
    if from_env:
        return from_env
    try:
        result = subprocess.run(
            ["git", "config", "user.email"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout.strip() or None


# ----------------------------------------------------------------------
# Identifier interconversion
# ----------------------------------------------------------------------


def _epmc_query(kind: str, value: str) -> str:
    if kind == "doi":
        return f'DOI:"{value}"'
    if kind == "pmid":
        return f"EXT_ID:{value} AND SRC:MED"
    if kind == "pmcid":
        return f"PMCID:{normalise_pmcid(value)}"
    raise ValueError(f"Europe PMC cannot be queried by {kind}")


def europepmc_record(kind: str, value: str, client: httpx.Client) -> dict[str, Any] | None:
    """The Europe PMC catalogue entry for one paper, or None."""
    response = client.get(
        f"{EUROPEPMC_BASE}/search",
        params={
            "query": _epmc_query(kind, value),
            "format": "json",
            "pageSize": 1,
            "resultType": "core",
        },
        timeout=45,
    )
    response.raise_for_status()
    results = (response.json().get("resultList") or {}).get("result") or []
    return results[0] if results else None


def metadata_from_europepmc(result: dict[str, Any]) -> Metadata:
    """The publication metadata in a Europe PMC entry, unaltered."""
    authors: list[str] = []
    for author in (result.get("authorList") or {}).get("author") or []:
        name = author.get("fullName") or author.get("collectiveName")
        if name:
            authors.append(str(name))
    year: int | None = None
    raw_year = result.get("pubYear")
    if raw_year and str(raw_year).isdigit():
        year = int(raw_year)
    return Metadata(
        source_api="europepmc",
        retrieved_at=now(),
        title=str(result["title"]).rstrip(".") if result.get("title") else None,
        authors=authors,
        year=year,
        journal=(result.get("journalInfo") or {}).get("journal", {}).get("title")
        or result.get("bookOrReportDetails", {}).get("publisher"),
        license=result.get("license"),
    )


def carry_europepmc_ids(record: Availability, result: dict[str, Any]) -> None:
    """Take the identifiers a Europe PMC entry carries onto the record."""
    at = now()
    for kind, raw, normalise in (
        ("doi", result.get("doi"), normalise_doi),
        ("pmid", result.get("pmid"), normalise_pmid),
        ("pmcid", result.get("pmcid"), normalise_pmcid),
    ):
        if not raw:
            continue
        try:
            value = normalise(str(raw))
        except Exception:  # a catalogue entry with a malformed id is not fatal
            continue
        add_id(record, kind, Identifier.returned(value, "europepmc", at))


def idconv(kind: str, value: str, client: httpx.Client) -> dict[str, str]:
    """PMID/PMCID/DOI interconversion via the NCBI ID converter.

    A second opinion on the identifiers Europe PMC already gives, and the only
    route for a paper Europe PMC does not hold. Returns whatever it knows,
    normalised; an unresolvable identifier gives an empty mapping rather than
    an error, because not being in PubMed Central is an ordinary fact about a
    paper.
    """
    try:
        response = client.get(
            IDCONV_URL,
            params={"ids": value, "format": "json", "tool": "paper-access"},
            timeout=45,
        )
        response.raise_for_status()
        records = response.json().get("records") or []
    except Exception as exc:
        logger.info("idconv lookup failed for %s %s: %s", kind, value, exc)
        return {}
    if not records or records[0].get("status") == "error":
        return {}
    entry = records[0]
    out: dict[str, str] = {}
    for key, target, normalise in (
        ("doi", "doi", normalise_doi),
        ("pmid", "pmid", normalise_pmid),
        ("pmcid", "pmcid", normalise_pmcid),
    ):
        raw = entry.get(key)
        if not raw:
            continue
        try:
            out[target] = normalise(str(raw))
        except Exception:
            continue
    return out


def search_candidates(
    text: str, client: httpx.Client, *, limit: int = 5
) -> list[dict[str, Any]]:
    """Papers that might be what a free-text query names.

    Europe PMC's relevance search, returned as candidates with enough metadata
    for a person to tell two same-year papers by the same group apart. Nothing
    here decides anything: the caller has to get a human to choose.
    """
    try:
        response = client.get(
            f"{EUROPEPMC_BASE}/search",
            params={
                "query": text,
                "format": "json",
                "pageSize": limit,
                "resultType": "core",
            },
            timeout=45,
        )
        response.raise_for_status()
        results = (response.json().get("resultList") or {}).get("result") or []
    except Exception as exc:
        logger.info("candidate search failed for %r: %s", text, exc)
        return []

    out: list[dict[str, Any]] = []
    for result in results:
        entry: dict[str, Any] = {"source_api": "europepmc"}
        for key, target in (("doi", "doi"), ("pmid", "pmid"), ("pmcid", "pmcid")):
            if result.get(key):
                entry[target] = str(result[key])
        meta = metadata_from_europepmc(result)
        entry["title"] = meta.title
        entry["authors"] = meta.authors[:8]
        entry["year"] = meta.year
        entry["journal"] = meta.journal
        if entry.get("doi") or entry.get("pmid") or entry.get("pmcid"):
            out.append(entry)
    return out


# ----------------------------------------------------------------------
# Rung 1: Europe PMC article XML
# ----------------------------------------------------------------------


def rung_europepmc(record: Availability, ctx: Context) -> Fetched | None:
    """Tagged article XML for the paper's PMC record.

    A paper can have a PMC record and still have no article XML behind it: an
    author-manuscript deposit is catalogued but not open, and its
    ``fullTextXML`` answers 404. That is 'unavailable' rather than 'failed' —
    there is nothing here to retry.
    """
    kind, value = record.primary_id
    try:
        result = europepmc_record(kind, value, ctx.client)
    except Exception as exc:
        record.attempts.append(
            Attempt("europepmc", "failed", f"search errored: {exc}", now())
        )
        return None

    if result is None:
        record.attempts.append(
            Attempt("europepmc", "unavailable", "no Europe PMC record for this paper", now())
        )
        return None

    carry_europepmc_ids(record, result)
    if record.metadata is None:
        record.metadata = metadata_from_europepmc(result)

    pmcid = result.get("pmcid")
    if not pmcid:
        record.attempts.append(
            Attempt("europepmc", "unavailable", "Europe PMC record carries no PMCID", now())
        )
        return None

    url = f"{EUROPEPMC_BASE}/{pmcid}/fullTextXML"
    try:
        response = ctx.client.get(url, timeout=90)
    except Exception as exc:
        record.attempts.append(
            Attempt("europepmc", "failed", f"{pmcid} fullTextXML: {exc}", now())
        )
        return None
    if response.status_code != 200:
        record.attempts.append(
            Attempt(
                "europepmc",
                "unavailable",
                f"{pmcid} is catalogued but its fullTextXML returned "
                f"{response.status_code} (open access: {result.get('isOpenAccess', 'unknown')})",
                now(),
            )
        )
        return None
    if "<article" not in response.text[:4000]:
        record.attempts.append(
            Attempt(
                "europepmc", "unavailable", f"{pmcid} fullTextXML is not a JATS article", now()
            )
        )
        return None

    record.attempts.append(Attempt("europepmc", "ok", f"article XML for {pmcid}", now()))
    return Fetched(kind="jats", body=response.content, url=url)


# ----------------------------------------------------------------------
# Rung 2: the preprint servers
# ----------------------------------------------------------------------


def preprint_metadata(
    doi: str, client: httpx.Client
) -> tuple[dict[str, Any] | None, str, list[str]]:
    """The preprint servers' record for this DOI, and which server has it.

    A server answering "no posts found" and a server not answering at all are
    reported separately, because they mean opposite things: the first settles
    that the paper is not a preprint, the second settles nothing. Recording an
    outage as the former would leave a preprint permanently marked as not one.
    """
    unreachable: list[str] = []
    for server in PREPRINT_SERVERS:
        try:
            response = client.get(f"{PREPRINT_DETAILS}/{server}/{doi}/na/json", timeout=30)
            response.raise_for_status()
            data = response.json()
        except Exception as exc:
            logger.info("%s details lookup failed for %s: %s", server, doi, exc)
            unreachable.append(f"{server}: {type(exc).__name__}")
            continue
        messages = data.get("messages") or [{}]
        if messages[0].get("status") != "ok":
            continue
        collection = data.get("collection") or []
        if collection:
            return collection[0], server, unreachable
    return None, "", unreachable


def normalise_jats_url(url: str) -> str:
    """Collapse the doubled slashes the details API sometimes returns.

    Highwire answers 404 for the literal path and 200 for the collapsed one.
    """
    scheme, _, rest = url.partition("://")
    return scheme + "://" + re.sub(r"/{2,}", "/", rest)


def rung_preprint_server(record: Availability, ctx: Context) -> Fetched | None:
    """The JATS a preprint server hosts, fetched past Cloudflare.

    A plain request gets a challenge page, so this needs TLS impersonation.
    That lives behind an optional extra, and its absence is 'skipped': nothing
    was learnt about the paper.
    """
    doi = record.ids.get("doi")
    if doi is None:
        record.attempts.append(
            Attempt(
                "preprint_server",
                "skipped",
                "the preprint servers are keyed by DOI and this paper has none",
                now(),
            )
        )
        return None

    meta, server, unreachable = preprint_metadata(doi.value, ctx.client)
    if not meta:
        answered = [s for s in PREPRINT_SERVERS if not any(u.startswith(s) for u in unreachable)]
        if unreachable:
            record.attempts.append(
                Attempt(
                    "preprint_server",
                    "failed",
                    f"could not reach {'; '.join(unreachable)}"
                    + (f" ({' and '.join(answered)} do not host it)" if answered else ""),
                    now(),
                )
            )
        else:
            record.attempts.append(
                Attempt(
                    "preprint_server",
                    "unavailable",
                    f"not hosted by {' or '.join(PREPRINT_SERVERS)}",
                    now(),
                )
            )
        return None

    jats_url = meta.get("jatsxml")
    if not jats_url:
        record.attempts.append(
            Attempt(
                "preprint_server", "unavailable", f"{server} record carries no JATS URL", now()
            )
        )
        return None
    jats_url = normalise_jats_url(jats_url)

    try:
        from curl_cffi import requests as impersonating
    except ImportError:
        record.attempts.append(
            Attempt(
                "preprint_server",
                "skipped",
                f"{server} hosts JATS at {jats_url} but getting past Cloudflare needs "
                "curl_cffi (the [text-access] extra)",
                now(),
            )
        )
        return None

    try:
        response = impersonating.get(jats_url, impersonate="chrome120", timeout=90)
    except Exception as exc:
        record.attempts.append(
            Attempt("preprint_server", "failed", f"{jats_url}: {exc}", now())
        )
        return None
    if response.status_code != 200:
        record.attempts.append(
            Attempt(
                "preprint_server",
                "failed",
                f"{jats_url} returned {response.status_code}",
                now(),
            )
        )
        return None
    if "<article" not in response.text[:4000]:
        record.attempts.append(
            Attempt(
                "preprint_server",
                "failed",
                f"{jats_url} did not return a JATS article, most likely a Cloudflare challenge",
                now(),
            )
        )
        return None

    record.attempts.append(Attempt("preprint_server", "ok", f"JATS from {server}", now()))
    return Fetched(kind="jats", body=response.content, url=jats_url)


# ----------------------------------------------------------------------
# Rung 3: an open-access PDF
# ----------------------------------------------------------------------


def oa_locations(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """The open-access locations in a resolver's answer, best first, deduplicated.

    The resolver's preferred location goes first and the rest follow, because
    the preferred one frequently names only a landing page while a later one
    has the PDF itself. Its vocabulary for host and version is carried through
    unchanged: mapping it onto ours would make a value it adds later look
    invalid, and the distinction that matters — a submitted version is the
    manuscript before review — is one a reader makes, not one to bake in.
    """
    ordered: list[dict[str, Any]] = []
    best = payload.get("best_oa_location")
    if isinstance(best, dict):
        ordered.append(best)
    for location in payload.get("oa_locations") or []:
        if isinstance(location, dict):
            ordered.append(location)

    seen: set[tuple[str, str]] = set()
    out: list[dict[str, Any]] = []
    for location in ordered:
        url = location.get("url") or ""
        pdf = location.get("url_for_pdf") or ""
        if not url and not pdf:
            continue
        if (url, pdf) in seen:
            continue
        seen.add((url, pdf))
        entry: dict[str, Any] = {}
        for key in ("url", "url_for_pdf", "host_type", "version"):
            value = location.get(key)
            if value:
                entry[key] = str(value)
        out.append(entry)
    return out


def download_pdf(url: str, ctx: Context) -> tuple[bytes | None, str]:
    """Download a PDF, working around hosts that fingerprint the client.

    Several publishers and repositories answer an ordinary Python HTTP client
    with a 403 or a challenge page while serving the same URL to a browser.
    Neither client gets past a host that genuinely requires a subscription.

    Returns:
        The bytes and an empty note, or ``None`` and why not. A response that
        is not a PDF is a failure however healthy its status code: a challenge
        page arrives as a cheerful 200.
    """
    attempts: list[str] = []
    getters: list[tuple[str, Callable[[], Any]]] = []
    try:
        from curl_cffi import requests as impersonating
    except ImportError:
        pass
    else:
        getters.append(
            ("impersonated", lambda: impersonating.get(url, impersonate="chrome120", timeout=120))
        )
    getters.append(("plain", lambda: ctx.client.get(url, timeout=120, follow_redirects=True)))

    for name, get in getters:
        try:
            response = get()
        except Exception as exc:
            attempts.append(f"{name}: {exc}")
            continue
        if response.status_code != 200:
            attempts.append(f"{name}: returned {response.status_code}")
            continue
        body = response.content
        if not body.startswith(b"%PDF"):
            attempts.append(f"{name}: returned {len(body)} bytes that are not a PDF")
            continue
        return body, ""
    return None, "could not be downloaded (" + "; ".join(attempts) + ")"


def rung_unpaywall(record: Availability, ctx: Context) -> Fetched | None:
    """An open-access PDF, where a resolver knows of one.

    Every location the resolver named is recorded, used or not, because
    deciding whether a location is the paper or a preprint of it cannot be done
    after the fact from a URL. Only locations naming the PDF directly are
    downloaded: a landing page would have to be scraped, which is fragile
    enough that asking a person is the better answer.
    """
    doi = record.ids.get("doi")
    if doi is None:
        record.attempts.append(
            Attempt(
                "unpaywall",
                "skipped",
                "the open-access resolver is keyed by DOI and this paper has none",
                now(),
            )
        )
        return None

    address = contact_email(ctx.contact)
    if not address:
        record.attempts.append(
            Attempt(
                "unpaywall",
                "skipped",
                "an open-access resolver needs a contact address; set "
                f"{CONTACT_ENV} or a git user.email",
                now(),
            )
        )
        return None

    url = (
        f"{UNPAYWALL_BASE}/{urllib.parse.quote(doi.value)}"
        f"?{urllib.parse.urlencode({'email': address})}"
    )
    try:
        response = ctx.client.get(url, timeout=45)
        response.raise_for_status()
        payload = response.json()
    except Exception as exc:
        record.attempts.append(Attempt("unpaywall", "failed", f"lookup errored: {exc}", now()))
        return None

    if record.metadata is None and payload.get("title"):
        record.metadata = Metadata(
            source_api="unpaywall",
            retrieved_at=now(),
            title=str(payload["title"]).rstrip("."),
            year=payload.get("year") if isinstance(payload.get("year"), int) else None,
            journal=payload.get("journal_name"),
            publisher=payload.get("publisher"),
        )

    locations = oa_locations(payload)
    record.oa_candidates = locations

    if not payload.get("is_oa") or not locations:
        record.attempts.append(
            Attempt("unpaywall", "unavailable", "no open-access location for this DOI", now())
        )
        return None

    with_pdf = [loc for loc in locations if loc.get("url_for_pdf")]
    if not with_pdf:
        described = "; ".join(
            f"{loc.get('host_type', 'unknown host')}/{loc.get('version', 'unknown version')}"
            for loc in locations
        )
        record.attempts.append(
            Attempt(
                "unpaywall",
                "unavailable",
                f"{len(locations)} open-access location(s) but none names a PDF "
                f"({described}); only landing pages are on offer",
                now(),
            )
        )
        return None

    failures: list[str] = []
    for location in with_pdf:
        pdf_url = location["url_for_pdf"]
        body, note = download_pdf(pdf_url, ctx)
        if body is None:
            failures.append(f"{pdf_url} {note}")
            continue
        location["used"] = True
        record.attempts.append(
            Attempt(
                "unpaywall",
                "ok",
                f"PDF from {location.get('host_type', 'unknown host')} "
                f"({location.get('version', 'unknown version')})",
                now(),
            )
        )
        return Fetched(kind="pdf", body=body, url=pdf_url)

    record.attempts.append(
        Attempt(
            "unpaywall",
            "failed",
            f"{len(with_pdf)} PDF link(s) named but none downloaded: " + "; ".join(failures),
            now(),
        )
    )
    return None
