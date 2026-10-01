"""The field mapping: which author columns feed which target field, and how.

Two preconditions here are easy to skip and expensive to skip.

A **scope filter**. Archive exports contain samples the project never ingested,
and a correctly-mapped term for a sample that is not in the atlas scores as an
error against the gold set while being entirely right. Out-of-scope rows are
kept and flagged, never dropped -- dropping them hides the discrepancy instead
of explaining it.

A **unit column**. Bare numeric ages are unmappable in isolation and the unit
routinely lives in a sibling column; sixty distinct values were once stranded
for exactly this reason.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .errors import OntomapError

FIELDS = ("species", "sex", "stage", "disease", "tissue")

ROLES = ("primary", "refinement", "qualifier")


@dataclass
class Source:
    column: str
    role: str = "primary"
    unit_column: str | None = None
    frame: str | None = None          # per-study stage reference frame

    @classmethod
    def parse(cls, raw: Any) -> Source:
        if isinstance(raw, str):
            return cls(column=raw)
        source = cls(
            column=raw["column"],
            role=raw.get("role", "primary"),
            unit_column=raw.get("unit_column"),
            frame=raw.get("frame"),
        )
        if source.role not in ROLES:
            raise OntomapError(f"unknown role {source.role!r}; expected one of {ROLES}")
        return source


@dataclass
class ScopeFilter:
    column: str
    include: list[Any]

    def admits(self, row: dict[str, Any]) -> bool:
        return row.get(self.column) in self.include


@dataclass
class Config:
    fields: dict[str, list[Source]] = field(default_factory=dict)
    scope_filter: ScopeFilter | None = None
    boundary: str = "during"          # how to read "N weeks"; see stage.parse
    placeholders: frozenset[str] = frozenset()
    study_organ: str | None = None

    @classmethod
    def load(cls, path: str | Path) -> Config:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls.from_dict(raw)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> Config:
        unknown = set(raw.get("fields", {})) - set(FIELDS)
        if unknown:
            raise OntomapError(f"unknown target field(s): {sorted(unknown)}")
        scope = raw.get("scope_filter")
        return cls(
            fields={
                name: [Source.parse(s) for s in sources]
                for name, sources in raw.get("fields", {}).items()
            },
            scope_filter=ScopeFilter(scope["column"], scope["include"]) if scope else None,
            boundary=raw.get("boundary", "during"),
            placeholders=frozenset(s.lower() for s in raw.get("placeholders", [])),
            study_organ=raw.get("study_organ"),
        )

    def columns(self) -> list[str]:
        wanted: list[str] = []
        for sources in self.fields.values():
            for source in sources:
                wanted.append(source.column)
                if source.unit_column:
                    wanted.append(source.unit_column)
        if self.scope_filter:
            wanted.append(self.scope_filter.column)
        return sorted(set(wanted))
