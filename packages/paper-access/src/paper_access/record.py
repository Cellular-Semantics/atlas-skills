"""The availability record: what is known about one paper's text.

The schema pins the shape. The cross-checks here pin what a record *means* — a
record claiming a route with nothing stored, or recovered text with no account
of its size, satisfies the schema and misleads every reader afterwards.

The one rule that is structural rather than a check: ``route`` says where the
usable content is and ``local_source`` says what is on disk, and they are
separate because a paper served only by ASTA has content and no bytes. Anything
downstream that needs a file must test for ``local_source``, never for a
route that merely looks successful.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

from .errors import PaperAccessError
from .ids import Identifier
from .supplements import Supplements, cross_check_supplements

SCHEMA_VERSION = 2
SCHEMA_NAME = "paper_availability.schema.json"

#: Routes that put bytes on disk. 'asta' and 'none' do not, which is the whole
#: reason route and local_source are separate fields.
ROUTES_WITH_BYTES = ("europepmc", "preprint_server", "unpaywall", "manual")


@lru_cache(maxsize=1)
def schema() -> dict[str, Any]:
    """The record schema, read from the package."""
    path = Path(__file__).parent / "schemas" / SCHEMA_NAME
    return json.loads(path.read_text(encoding="utf-8"))


@dataclass
class Attempt:
    """One rung of the waterfall and what it did."""

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
    def from_dict(cls, payload: dict[str, Any]) -> Attempt:
        return cls(
            route=payload["route"],
            outcome=payload["outcome"],
            note=payload.get("note"),
            at=payload.get("at"),
        )


@dataclass
class LocalSource:
    """Bytes on disk, and what they are."""

    kind: str
    path: str
    sha256: str
    bytes: int
    url: str | None = None
    text_file: str | None = None
    text_quality: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "kind": self.kind,
            "path": self.path,
            "sha256": self.sha256,
            "bytes": self.bytes,
        }
        for key in ("url", "text_file", "text_quality"):
            value = getattr(self, key)
            if value:
                out[key] = value
        return out

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> LocalSource:
        return cls(
            kind=payload["kind"],
            path=payload["path"],
            sha256=payload["sha256"],
            bytes=int(payload["bytes"]),
            url=payload.get("url"),
            text_file=payload.get("text_file"),
            text_quality=payload.get("text_quality"),
        )


@dataclass
class AstaIndexing:
    """How much of this paper ASTA's snippet index holds."""

    band: str
    probed_at: str
    corpus_id: str | None = None
    n_snippets: int = 0
    n_chars: int = 0
    n_sections: int = 0
    n_ref_mentions: int = 0
    limit: int | None = None
    reason: str = ""

    @property
    def servable(self) -> bool:
        """Whether ASTA holds enough of this paper to be worth querying."""
        return self.band == "full"

    @property
    def measured(self) -> bool:
        """Whether the probe actually learnt anything.

        A 'skipped' band is not a band: it means the probe could not run, which
        is a different finding from 'unindexed' and must never be reported as
        one.
        """
        return self.band != "skipped"

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"band": self.band, "probed_at": self.probed_at}
        if self.corpus_id:
            out["corpus_id"] = self.corpus_id
        for key in ("n_snippets", "n_chars", "n_sections", "n_ref_mentions"):
            out[key] = getattr(self, key)
        if self.limit:
            out["limit"] = self.limit
        if self.reason:
            out["reason"] = self.reason
        # Recorded rather than left implicit: ASTA does not index figure or
        # table legends, and a reader of an ASTA-only paper has to know that.
        out["has_figure_legends"] = False
        return out

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> AstaIndexing:
        return cls(
            band=payload["band"],
            probed_at=payload["probed_at"],
            corpus_id=payload.get("corpus_id"),
            n_snippets=int(payload.get("n_snippets") or 0),
            n_chars=int(payload.get("n_chars") or 0),
            n_sections=int(payload.get("n_sections") or 0),
            n_ref_mentions=int(payload.get("n_ref_mentions") or 0),
            limit=payload.get("limit"),
            reason=payload.get("reason") or "",
        )


@dataclass
class Metadata:
    """Publication metadata exactly as one API returned it."""

    source_api: str
    retrieved_at: str
    title: str | None = None
    authors: list[str] = field(default_factory=list)
    year: int | None = None
    journal: str | None = None
    publisher: str | None = None
    license: str | None = None

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "source_api": self.source_api,
            "retrieved_at": self.retrieved_at,
        }
        for key in ("title", "year", "journal", "publisher", "license"):
            value = getattr(self, key)
            if value:
                out[key] = value
        if self.authors:
            out["authors"] = list(self.authors)
        return out

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> Metadata:
        return cls(
            source_api=payload["source_api"],
            retrieved_at=payload["retrieved_at"],
            title=payload.get("title"),
            authors=list(payload.get("authors") or []),
            year=payload.get("year"),
            journal=payload.get("journal"),
            publisher=payload.get("publisher"),
            license=payload.get("license"),
        )


@dataclass
class Availability:
    """One paper's availability record, conforming to the schema."""

    input: str
    ids: dict[str, Identifier] = field(default_factory=dict)
    route: str = "none"
    local_source: LocalSource | None = None
    asta: AstaIndexing | None = None
    metadata: Metadata | None = None
    attempts: list[Attempt] = field(default_factory=list)
    oa_candidates: list[dict[str, Any]] = field(default_factory=list)
    gap: dict[str, str] | None = None
    notes: str | None = None
    supplements: Supplements | None = None
    fetched_at: str | None = None
    attempted_at: str | None = None

    # -- identifiers ------------------------------------------------------

    @property
    def confirmed_ids(self) -> dict[str, Identifier]:
        return {k: v for k, v in self.ids.items() if v.confirmed}

    @property
    def primary_id(self) -> tuple[str, str]:
        """The identifier this paper is filed under.

        DOI first because it is the one the rest of the world uses, then PMCID,
        then PMID. A record with no confirmed identifier cannot be filed, and
        saying so here beats writing it somewhere arbitrary.
        """
        for kind in ("doi", "pmcid", "pmid"):
            found = self.ids.get(kind)
            if found is not None and found.confirmed:
                return kind, found.value
        raise PaperAccessError(
            f"{self.input!r} has no confirmed identifier; it is a candidate, and "
            "`fetch` needs a person to confirm it first"
        )

    @property
    def title(self) -> str | None:
        return self.metadata.title if self.metadata else None

    def id_values(self) -> set[str]:
        """Every identifier value on this record, confirmed or not."""
        return {found.value for found in self.ids.values()}

    # -- serialisation ----------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "input": self.input,
            "ids": {kind: found.to_dict() for kind, found in self.ids.items()},
            "route": self.route,
        }
        if self.local_source:
            out["local_source"] = self.local_source.to_dict()
        if self.asta:
            out["asta"] = self.asta.to_dict()
        if self.metadata:
            out["metadata"] = self.metadata.to_dict()
        out["attempts"] = [a.to_dict() for a in self.attempts]
        if self.oa_candidates:
            out["oa_candidates"] = self.oa_candidates
        if self.gap:
            out["gap"] = self.gap
        if self.notes:
            out["notes"] = self.notes
        if self.supplements is not None:
            out["supplements"] = self.supplements.to_dict()
        for key in ("fetched_at", "attempted_at"):
            value = getattr(self, key)
            if value:
                out[key] = value
        return out

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> Availability:
        version = payload.get("schema_version")
        if version != SCHEMA_VERSION:
            raise PaperAccessError(
                f"record is schema_version {version!r}, this build writes "
                f"{SCHEMA_VERSION}; refusing to guess at the difference"
            )
        local = payload.get("local_source")
        asta = payload.get("asta")
        meta = payload.get("metadata")
        return cls(
            input=payload["input"],
            ids={k: Identifier.from_dict(v) for k, v in (payload.get("ids") or {}).items()},
            route=payload.get("route", "none"),
            local_source=LocalSource.from_dict(local) if local else None,
            asta=AstaIndexing.from_dict(asta) if asta else None,
            metadata=Metadata.from_dict(meta) if meta else None,
            attempts=[Attempt.from_dict(a) for a in payload.get("attempts") or []],
            oa_candidates=list(payload.get("oa_candidates") or []),
            gap=payload.get("gap"),
            notes=payload.get("notes"),
            supplements=(
                Supplements.from_dict(payload["supplements"])
                if payload.get("supplements") is not None
                else None
            ),
            fetched_at=payload.get("fetched_at"),
            attempted_at=payload.get("attempted_at"),
        )


# ----------------------------------------------------------------------
# Validation
# ----------------------------------------------------------------------


def validate(payload: dict[str, Any]) -> None:
    """Validate a record against the schema.

    Raises:
        PaperAccessError: On the first violation, with the JSON path.
    """
    import jsonschema

    try:
        jsonschema.validate(payload, schema())
    except jsonschema.ValidationError as exc:
        location = "/".join(str(part) for part in exc.absolute_path) or "(root)"
        raise PaperAccessError(f"record invalid at {location}: {exc.message}") from exc


def cross_check(payload: dict[str, Any]) -> list[str]:
    """Consistency rules the schema cannot express.

    Returns:
        Human-readable problems, empty if the record is consistent.
    """
    problems: list[str] = []
    route = payload.get("route")
    local = payload.get("local_source")
    attempts = payload.get("attempts") or []
    succeeded = [a for a in attempts if a.get("outcome") == "ok"]
    # The probe always runs and always records an attempt, but it never
    # produces bytes, so it is not one of the rungs a route can come from.
    producing = [a for a in succeeded if a.get("route") != "asta_probe"]

    if route in ROUTES_WITH_BYTES:
        if not local:
            problems.append(f"route is '{route}' but nothing is recorded on disk")
        if not payload.get("fetched_at"):
            problems.append(f"route is '{route}' but fetched_at is missing")
        if payload.get("gap"):
            problems.append(f"route is '{route}' but a gap is recorded as well")
        if len(producing) != 1:
            problems.append(
                f"expected exactly one rung to have produced this paper, found {len(producing)}"
            )
        elif producing[0].get("route") not in (route, "local"):
            problems.append(
                f"route is '{route}' but the successful rung was '{producing[0].get('route')}'"
            )
    elif route == "asta":
        if local:
            problems.append(
                "route is 'asta' but bytes are recorded on disk; a paper with a local "
                "source is served from it, not from the index"
            )
        band = (payload.get("asta") or {}).get("band")
        if band != "full":
            problems.append(
                f"route is 'asta' but the measured band is {band!r}; only 'full' holds "
                "enough of a paper to serve"
            )
        if producing:
            problems.append(
                f"route is 'asta' but rung '{producing[0].get('route')}' is recorded as ok"
            )
    elif route == "none":
        if local:
            problems.append("route is 'none' but bytes are recorded on disk")
        if payload.get("fetched_at"):
            problems.append("route is 'none' but fetched_at is set")
        if not payload.get("gap"):
            problems.append("route is 'none' but no gap says what to ask for")
        if producing:
            problems.append(
                f"route is 'none' but rung '{producing[0].get('route')}' is recorded as ok"
            )

    if local:
        if local.get("kind") == "jats" and local.get("text_file"):
            problems.append("a JATS source is parsed directly and should carry no text_file")
        if local.get("text_file") and not local.get("text_quality"):
            problems.append(
                "text_file is set but text_quality does not say how much text there is"
            )
        if local.get("text_quality") and not local.get("text_file"):
            problems.append("text_quality is set but no text_file was written")

    ids = payload.get("ids") or {}
    if not any(v.get("confirmed", True) for v in ids.values()):
        problems.append(
            "no confirmed identifier: this is a candidate record and nothing may be "
            "fetched or cited against it"
        )
    for kind, found in ids.items():
        if found.get("from") == "input" and found.get("at"):
            problems.append(f"{kind} came from the caller but carries a lookup time")

    supplements = payload.get("supplements")
    if supplements is not None:
        problems.extend(
            f"supplements: {problem}" for problem in cross_check_supplements(supplements)
        )

    used = [loc for loc in payload.get("oa_candidates") or [] if loc.get("used")]
    if len(used) > 1:
        problems.append(f"{len(used)} open-access locations are marked as used")
    if used and route != "unpaywall":
        problems.append(f"an open-access location is marked used but the route is '{route}'")

    return problems


def check(payload: dict[str, Any]) -> list[str]:
    """Schema and consistency together, as a list of problems."""
    try:
        validate(payload)
    except PaperAccessError as exc:
        return [str(exc)]
    return cross_check(payload)
