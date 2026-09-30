"""A paper's supplementary material: what files it has, and what arrived.

Retrieval only. Nothing here reads what a supplement *says* — no spreadsheet is
opened, no prose extracted, no relevance judged. A retrieved file is an opaque
blob with a label on it.

What is recorded is what the publisher already told us: the filename, the media
type, the size, the archive's own member table, and any description the authors
wrote. That last one is a machine fact and not annotation, provided two rules
hold, and they are enforced here rather than left to good intentions:

* A description is **harvested verbatim** from one named source, never composed,
  paraphrased or merged. Where two sources disagree the article XML wins and the
  other is noted.
* A file whose job is to **describe** the bundle may be read; a data file may
  not. That distinction is the whole boundary of this phase, so the recognition
  test is one function — :func:`looks_like_manifest` — with its own tests,
  rather than a condition spread across the fetchers.

Two outcomes exist here that the paper waterfall has no need of. ``listed``
means the file is known to exist and its bytes were not fetched, which is worth
recording on its own: it is the difference between "eleven supplements nobody
could get" and "this paper appears to have none". ``deferred`` means a fetch was
declined — so far only on size — and nothing was learnt about whether it could
have succeeded. Neither may be read as "unavailable".
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .ids import now

#: Extensions we will name a media type for. A guess about the container, never
#: about the contents.
MEDIA_TYPES = {
    ".xlsx": "xlsx", ".xls": "xls", ".csv": "csv", ".tsv": "tsv", ".txt": "txt",
    ".pdf": "pdf", ".docx": "docx", ".doc": "doc", ".zip": "zip", ".gz": "gz",
    ".tar": "tar", ".json": "json", ".xml": "xml", ".html": "html",
    ".png": "png", ".jpg": "jpg", ".jpeg": "jpg", ".tif": "tif", ".tiff": "tif",
    ".eps": "eps", ".svg": "svg", ".mp4": "mp4", ".mov": "mov", ".avi": "avi",
    ".h5ad": "h5ad", ".h5": "h5", ".rds": "rds", ".mtx": "mtx",
}

#: Figure images bloat a bundle and are not evidence about cell types. Skipped
#: on extraction, but still listed as members: a skip a reader cannot see is
#: indistinguishable from a file that was never there.
FIGURE_MEDIA = {"png", "jpg", "tif", "eps", "svg"}

#: Media types large enough to be worth a generous per-member cap, because a
#: results table legitimately runs to hundreds of megabytes.
TABULAR_MEDIA = {"csv", "tsv", "txt", "xlsx", "xls", "mtx"}

#: Names a bundle's own index goes by. Matched case-insensitively against the
#: stem, so `MANIFEST.txt`, `file_list.csv` and `README` all qualify.
MANIFEST_STEMS = ("manifest", "index", "readme", "contents", "file_list", "filelist")

#: A bundle index is small. Anything larger is a data file whose name happens to
#: be unfortunate, and reading it would cross out of this phase.
MANIFEST_MAX_BYTES = 256 * 1024


def media_type(name: str) -> str:
    """The media type implied by a filename's extension, or ``""``."""
    return MEDIA_TYPES.get(Path(name).suffix.lower(), "")


def looks_like_manifest(name: str, size_bytes: int | None = None) -> bool:
    """Whether a file's job is to describe the bundle rather than to be data.

    The single place this phase's boundary is decided. A file that passes may be
    read for the labels it gives other files; everything else is opaque. Both
    conditions matter: a results table called ``index.csv`` is data, and a
    40 MB ``README.pdf`` is a manuscript.
    """
    stem = Path(name).stem.lower()
    if not any(stem == s or stem.startswith(s) for s in MANIFEST_STEMS):
        return False
    if size_bytes is not None and size_bytes > MANIFEST_MAX_BYTES:
        return False
    return media_type(name) in ("txt", "csv", "tsv", "json", "xml", "html", "")


# ----------------------------------------------------------------------
# Record types
# ----------------------------------------------------------------------


@dataclass
class SupplementAttempt:
    """One rung and what it did."""

    route: str
    outcome: str
    note: str | None = None
    at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"route": self.route, "outcome": self.outcome}
        if self.note:
            out["note"] = self.note
        if self.at:
            out["at"] = self.at
        return out

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> SupplementAttempt:
        return cls(
            route=payload["route"],
            outcome=payload["outcome"],
            note=payload.get("note"),
            at=payload.get("at"),
        )


@dataclass
class SupplementRetrieval:
    """How one file arrived, or why it did not."""

    route: str = "none"
    url: str | None = None
    retrieved_at: str | None = None
    attempted_at: str | None = None
    note: str | None = None

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"route": self.route}
        for key in ("url", "retrieved_at", "attempted_at", "note"):
            value = getattr(self, key)
            if value:
                out[key] = value
        return out

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> SupplementRetrieval:
        return cls(
            route=payload.get("route", "none"),
            url=payload.get("url"),
            retrieved_at=payload.get("retrieved_at"),
            attempted_at=payload.get("attempted_at"),
            note=payload.get("note"),
        )


@dataclass
class ArchiveMember:
    """One entry in an archive's member table."""

    member_path: str
    extracted: bool = False
    media_type: str = ""
    size_bytes: int | None = None
    path: str | None = None
    note: str | None = None

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "member_path": self.member_path,
            "extracted": self.extracted,
        }
        if self.media_type:
            out["media_type"] = self.media_type
        if self.size_bytes is not None:
            out["size_bytes"] = self.size_bytes
        if self.path:
            out["path"] = self.path
        if self.note:
            out["note"] = self.note
        return out

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> ArchiveMember:
        return cls(
            member_path=payload["member_path"],
            extracted=bool(payload.get("extracted")),
            media_type=payload.get("media_type", ""),
            size_bytes=payload.get("size_bytes"),
            path=payload.get("path"),
            note=payload.get("note"),
        )


@dataclass
class SupplementFile:
    """One supplementary file as the publisher packages it."""

    file_id: str
    status: str = "listed"
    filename: str | None = None
    media_type: str = ""
    label: str | None = None
    description: str | None = None
    description_source: str | None = None
    size_bytes: int | None = None
    sha256: str | None = None
    path: str | None = None
    retrieval: SupplementRetrieval = field(default_factory=SupplementRetrieval)
    members: list[ArchiveMember] = field(default_factory=list)

    def describe(self, text: str, source: str) -> None:
        """Attach a harvested description, keeping the better-attested one.

        Verbatim or not at all: the text is stored as given. Where a second
        source offers a different description the first is kept and the second
        recorded as a note, because a blended description cannot be checked
        against anything. The article XML is harvested first, so it wins.
        """
        text = text.strip()
        if not text:
            return
        if self.description is None:
            self.description = text
            self.description_source = source
            return
        if text == self.description:
            return
        addition = f"{source} says: {text}"
        note = self.retrieval.note
        self.retrieval.note = f"{note}; {addition}" if note else addition

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"file_id": self.file_id, "status": self.status}
        for key in ("filename", "media_type", "label", "description",
                    "description_source", "sha256", "path"):
            value = getattr(self, key)
            if value:
                out[key] = value
        if self.size_bytes is not None:
            out["size_bytes"] = self.size_bytes
        out["retrieval"] = self.retrieval.to_dict()
        if self.members:
            out["members"] = [m.to_dict() for m in self.members]
        return out

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> SupplementFile:
        return cls(
            file_id=payload["file_id"],
            status=payload.get("status", "listed"),
            filename=payload.get("filename"),
            media_type=payload.get("media_type", ""),
            label=payload.get("label"),
            description=payload.get("description"),
            description_source=payload.get("description_source"),
            size_bytes=payload.get("size_bytes"),
            sha256=payload.get("sha256"),
            path=payload.get("path"),
            retrieval=SupplementRetrieval.from_dict(payload.get("retrieval") or {}),
            members=[ArchiveMember.from_dict(m) for m in payload.get("members") or []],
        )


@dataclass
class Supplements:
    """Everything known about one paper's supplementary material."""

    files: list[SupplementFile] = field(default_factory=list)
    listing_sources: list[SupplementAttempt] = field(default_factory=list)
    attempts: list[SupplementAttempt] = field(default_factory=list)
    gaps: list[dict[str, Any]] = field(default_factory=list)
    listed_at: str | None = None
    fetched_at: str | None = None
    attempted_at: str | None = None

    def by_id(self, file_id: str) -> SupplementFile | None:
        for found in self.files:
            if found.file_id == file_id:
                return found
        return None

    def add(self, entry: SupplementFile) -> SupplementFile:
        """Take a listed file in, merging into an existing entry of that name."""
        existing = self.by_id(entry.file_id)
        if existing is None:
            self.files.append(entry)
            return entry
        if entry.description and not existing.description:
            existing.describe(entry.description, entry.description_source or "jats_caption")
        if entry.label and not existing.label:
            existing.label = entry.label
        if entry.size_bytes is not None and existing.size_bytes is None:
            existing.size_bytes = entry.size_bytes
        if entry.media_type and not existing.media_type:
            existing.media_type = entry.media_type
        return existing

    @property
    def counts(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for found in self.files:
            out[found.status] = out.get(found.status, 0) + 1
        return out

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"files": [f.to_dict() for f in self.files]}
        if self.listing_sources:
            out["listing_sources"] = [a.to_dict() for a in self.listing_sources]
        if self.attempts:
            out["attempts"] = [a.to_dict() for a in self.attempts]
        if self.gaps:
            out["gaps"] = self.gaps
        for key in ("listed_at", "fetched_at", "attempted_at"):
            value = getattr(self, key)
            if value:
                out[key] = value
        return out

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> Supplements:
        return cls(
            files=[SupplementFile.from_dict(f) for f in payload.get("files") or []],
            listing_sources=[
                SupplementAttempt.from_dict(a) for a in payload.get("listing_sources") or []
            ],
            attempts=[SupplementAttempt.from_dict(a) for a in payload.get("attempts") or []],
            gaps=list(payload.get("gaps") or []),
            listed_at=payload.get("listed_at"),
            fetched_at=payload.get("fetched_at"),
            attempted_at=payload.get("attempted_at"),
        )


# ----------------------------------------------------------------------
# Consistency
# ----------------------------------------------------------------------


def cross_check_supplements(payload: dict[str, Any]) -> list[str]:
    """Rules about the supplements block the schema cannot express."""
    problems: list[str] = []
    files = payload.get("files") or []

    seen: set[str] = set()
    for entry in files:
        file_id = entry.get("file_id", "?")
        if file_id in seen:
            problems.append(f"{file_id}: listed twice")
        seen.add(file_id)

        status = entry.get("status")
        retrieval = entry.get("retrieval") or {}

        if status == "present":
            for key in ("path", "size_bytes"):
                if not entry.get(key):
                    problems.append(f"{file_id}: status is 'present' but {key} is missing")
            if retrieval.get("route") in (None, "none", "jats_listing"):
                problems.append(
                    f"{file_id}: status is 'present' but no route is recorded as having "
                    "produced it"
                )
        else:
            if entry.get("path"):
                problems.append(f"{file_id}: status is {status!r} but a stored path is set")
            if entry.get("sha256"):
                problems.append(f"{file_id}: status is {status!r} but a digest is set")

        if status == "deferred" and not retrieval.get("note"):
            problems.append(
                f"{file_id}: status is 'deferred' but nothing says why, so a reader "
                "cannot tell it from a file nobody could get"
            )

        if entry.get("description") and not entry.get("description_source"):
            problems.append(
                f"{file_id}: has a description with no source, so it cannot be told "
                "apart from one somebody wrote"
            )
        if entry.get("description_source") and not entry.get("description"):
            problems.append(f"{file_id}: names a description source but carries no description")

        for member in entry.get("members") or []:
            if member.get("extracted") and not member.get("path"):
                problems.append(
                    f"{file_id}/{member.get('member_path')}: marked extracted with nowhere stored"
                )
            if not member.get("extracted") and member.get("path"):
                problems.append(
                    f"{file_id}/{member.get('member_path')}: not extracted but has a path"
                )

    deferred = [f for f in files if f.get("status") == "deferred"]
    gap_ids = {g.get("file_id") for g in payload.get("gaps") or []}
    for entry in deferred:
        if entry.get("file_id") not in gap_ids:
            problems.append(
                f"{entry.get('file_id')}: deferred but no gap says what would fetch it"
            )

    return problems


# ----------------------------------------------------------------------
# Data-availability statements
# ----------------------------------------------------------------------

#: Repositories a data-availability statement commonly points at. Recognised so
#: the pointer can be reported, never so it can be scraped: an accession is
#: already actionable, and crawling arbitrary hosts is not this tool's job.
REPOSITORY_PATTERNS = (
    ("GEO", re.compile(r"\bGSE\d{3,}\b")),
    ("ArrayExpress", re.compile(r"\bE-[A-Z]{4}-\d+\b")),
    ("Zenodo", re.compile(r"\bzenodo\.org/record/\d+|10\.5281/zenodo\.\d+", re.I)),
    ("figshare", re.compile(r"\bfigshare\.com/[^\s)]+", re.I)),
    ("Dryad", re.compile(r"\b10\.5061/dryad\.[^\s)]+", re.I)),
    ("SRA", re.compile(r"\bPRJ[EDN][A-Z]\d+\b")),
    ("BioStudies", re.compile(r"\bS-[A-Z]{4}\d+\b")),
)

_AVAILABILITY_CUE = re.compile(
    r"(data|code|materials?)\s+(availability|accessibility)|available (at|from|in)"
    r"|deposited (in|at)|accession (number|code)",
    re.I,
)


def find_pointers(text: str) -> list[dict[str, str]]:
    """Repository pointers a paper's text names, with the sentence around them.

    A pointer is a gap with an address, not a file to go and get. The sentence
    is kept because an accession on its own rarely says which of a paper's
    datasets it is.
    """
    out: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for sentence in re.split(r"(?<=[.!?])\s+", text):
        if len(sentence) > 600:
            sentence = sentence[:600]
        for name, pattern in REPOSITORY_PATTERNS:
            for match in pattern.finditer(sentence):
                key = (name, match.group(0))
                if key in seen:
                    continue
                seen.add(key)
                out.append({
                    "repository": name,
                    "accession": match.group(0),
                    "context": " ".join(sentence.split()),
                })
    if not out:
        return out
    # A statement with no availability cue anywhere is a weaker signal; keep it,
    # but say so rather than presenting a bare accession as a finding.
    if not _AVAILABILITY_CUE.search(text):
        for entry in out:
            entry["note"] = "no data-availability wording nearby; accession found in passing"
    return out


def pointer_gap(pointer: dict[str, str]) -> dict[str, Any]:
    """A repository pointer, said as a gap somebody can act on."""
    accession = pointer["accession"]
    repository = pointer["repository"]
    gap: dict[str, Any] = {
        "what": f"{repository} {accession}",
        "reason": (
            "the paper points at a repository rather than attaching the data; "
            "this tool deliberately does not fetch from arbitrary hosts"
        ),
        "action": f"retrieve {accession} from {repository} yourself if it is wanted",
    }
    if pointer.get("context"):
        gap["action"] += f' — the paper says: "{pointer["context"]}"'
    return gap


def now_stamp() -> str:
    return now()
