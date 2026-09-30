"""Identifiers, and where each one came from.

Everything an agent gets wrong about a literature corpus, it gets wrong here. A
DOI one character out resolves to a different paper, or to nothing, and no
reader of the resulting report can tell. So an identifier enters a record by
exactly two routes and there is no third: the caller supplied it, or a named API
returned it at a recorded time. :class:`Identifier` carries that provenance as
part of the value rather than beside it, which is what lets the record be
checked afterwards.

Free-text input — a citation string, an author and a year — is resolved to
*candidates*, never to a confirmed identifier. Two papers by the same group in
the same year on the same tissue is the normal case in this literature, so a
title match is a proposal for a person to accept, not an answer.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

from .errors import PaperAccessError

IdKind = Literal["doi", "pmid", "pmcid"]

#: Sources an identifier may carry. There is deliberately no "inferred".
ID_SOURCES = ("input", "europepmc", "idconv", "crossref", "unpaywall", "asta")

DOI_RE = re.compile(r"10\.\d{4,9}/[^\s\"'<>]+")
_DOI_FULL_RE = re.compile(r"^10\.\d{4,9}/\S+$")
_PMID_RE = re.compile(r"^\d{1,8}$")
_PMCID_RE = re.compile(r"^PMC\d+$", re.IGNORECASE)

#: Trailing punctuation a DOI picks up from running text or a PDF's front
#: matter. Stripped from the right only, since all of these are legal *inside*
#: a DOI and only a trailing one is suspect.
_DOI_TRAILING = ".,;:)]}>\"'"


def now() -> str:
    """An ISO-8601 UTC timestamp, to the second."""
    return datetime.now(UTC).isoformat(timespec="seconds")


@dataclass(frozen=True)
class Identifier:
    """One identifier and the provenance of how it got here.

    ``confirmed`` is false for something a free-text search proposed and nobody
    has accepted. The waterfall refuses to fetch such a record: acting on an
    unconfirmed identifier is the failure this whole module exists to prevent.
    """

    value: str
    source: str
    at: str | None = None
    confirmed: bool = True

    def __post_init__(self) -> None:
        if self.source not in ID_SOURCES:
            raise PaperAccessError(
                f"{self.source!r} is not a known identifier source; expected one of "
                + ", ".join(ID_SOURCES)
            )

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"value": self.value, "from": self.source}
        if self.at:
            out["at"] = self.at
        if not self.confirmed:
            out["confirmed"] = False
        return out

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> Identifier:
        return cls(
            value=payload["value"],
            source=payload["from"],
            at=payload.get("at"),
            confirmed=bool(payload.get("confirmed", True)),
        )

    @classmethod
    def given(cls, value: str) -> Identifier:
        """An identifier the caller supplied, taken as given."""
        return cls(value=value, source="input")

    @classmethod
    def returned(cls, value: str, source: str, at: str | None = None) -> Identifier:
        """An identifier an API returned."""
        return cls(value=value, source=source, at=at or now())


def normalise_doi(raw: str) -> str:
    """A DOI with its prefixes and trailing punctuation removed, lowercased.

    DOIs are case-insensitive for comparison, and a store that keeps two
    directories for one paper because a publisher shouted its suffix is a store
    that fetches the same paper twice.
    """
    value = raw.strip()
    for prefix in ("https://doi.org/", "http://doi.org/", "https://dx.doi.org/", "doi:"):
        if value.lower().startswith(prefix):
            value = value[len(prefix) :]
            break
    value = value.strip().rstrip(_DOI_TRAILING)
    if not _DOI_FULL_RE.match(value):
        raise PaperAccessError(f"{raw!r} is not a DOI")
    return value.lower()


def normalise_pmid(raw: str) -> str:
    """A PMID as bare digits."""
    value = raw.strip()
    if value.lower().startswith("pmid:"):
        value = value[5:].strip()
    # Leading zeros come from fixed-width exports and are not part of the id,
    # so they are stripped before the length is judged.
    if value.isdigit():
        value = value.lstrip("0") or "0"
    if not _PMID_RE.match(value):
        raise PaperAccessError(f"{raw!r} is not a PMID")
    return value


def normalise_pmcid(raw: str) -> str:
    """A PMCID as ``PMC`` followed by digits."""
    value = raw.strip()
    if value.lower().startswith("pmcid:"):
        value = value[6:].strip()
    if value.isdigit():
        value = f"PMC{value}"
    if not _PMCID_RE.match(value):
        raise PaperAccessError(f"{raw!r} is not a PMCID")
    return "PMC" + value[3:]


def parse_id(raw: str) -> tuple[IdKind, str]:
    """Recognise and normalise an exact identifier.

    Accepts an explicit ``DOI:``/``PMID:``/``PMCID:`` prefix, a doi.org URL, a
    bare DOI, a bare ``PMC…``, or bare digits. Anything else is not an exact
    identifier — which is a fact about the input, not an error in it, so callers
    that accept free text should catch this and resolve instead.

    Raises:
        PaperAccessError: The string is not an exact identifier.
    """
    value = raw.strip()
    low = value.lower()
    if low.startswith("doi:") or (low.startswith(("http://", "https://")) and "doi.org/" in low):
        return "doi", normalise_doi(value)
    if low.startswith("pmid:"):
        return "pmid", normalise_pmid(value)
    if low.startswith("pmcid:") or _PMCID_RE.match(value):
        return "pmcid", normalise_pmcid(value)
    if value.startswith("10."):
        return "doi", normalise_doi(value)
    if _PMID_RE.match(value):
        return "pmid", normalise_pmid(value)
    raise PaperAccessError(
        f"{raw!r} is not an exact identifier. A DOI, a PMID, a PMCID or a doi.org "
        "URL is taken as given; anything else has to go through `resolve`, which "
        "returns candidates for a person to confirm."
    )


def looks_exact(raw: str) -> bool:
    """Whether :func:`parse_id` would accept this string."""
    try:
        parse_id(raw)
    except PaperAccessError:
        return False
    return True


def find_ids(text: str) -> dict[str, set[str]]:
    """Every identifier mentioned in a block of text, by kind.

    Used to check a written document's citations against a store. Deliberately
    greedy on DOIs and conservative on the numeric kinds: a bare number in prose
    is a number, so a PMID only counts when it announces itself.
    """
    found: dict[str, set[str]] = {"doi": set(), "pmid": set(), "pmcid": set()}
    for match in DOI_RE.finditer(text):
        try:
            found["doi"].add(normalise_doi(match.group(0)))
        except PaperAccessError:
            continue
    for match in re.finditer(r"\bPMC\d+\b", text, re.IGNORECASE):
        found["pmcid"].add(normalise_pmcid(match.group(0)))
    for match in re.finditer(r"\bPMID[:\s]\s*(\d{1,8})\b", text, re.IGNORECASE):
        found["pmid"].add(normalise_pmid(match.group(1)))
    return found


def slug(kind: IdKind, value: str) -> str:
    """A directory name for one paper.

    A DOI's slash becomes an underscore and anything else awkward becomes a
    hyphen, which keeps the common case legible — ``10.1038_s41586-023-06812-z``
    is recognisably a paper — without inventing a hashing scheme for the
    pathological ones.
    """
    base = value.replace("/", "_") if kind == "doi" else f"{kind}_{value}"
    return re.sub(r"[^A-Za-z0-9._-]", "-", base)
