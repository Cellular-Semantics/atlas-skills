"""Human stage windows for UBERON anatomy, and a second opinion on precursors.

The chain, which closes completely:

    UBERON --hasDbXref--> EHDAA2 --starts_at/ends_at--> HsapDv --dpf--> a day

1,835 UBERON terms carry an ``EHDAA2:`` xref; 2,444 of 2,459 EHDAA2 terms have
``starts_at``, every one of them onto a HsapDv stage term; and HsapDv stage
terms carry day windows. So the same day value that resolved the stage field can
be tested against the anatomy, which is the strongest form of "tissue depends on
the other fields" available.

Most terms give a **lower bound only** -- 1,058 of 2,444 have both ends. That is
the useful direction anyway: a lower bound refutes a precursor as too late for
an early sample, and refutation is what stops a wrong assignment.

EHDAA2 is inactive in OBO Foundry and frozen at releases/2024-01-11. Inactive is
not obsolete: it is finished, which makes it a pinned data dependency that
cannot drift. It is vendored (see ``tools/build_tables.py``) because it is also
not loaded in Ubergraph -- its IRIs appear there only as dangling objects of
``hsapdv#has_stage_marker``, with no labels and no axioms.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from importlib import resources
from typing import Any

from .stage import stage_table
from .ubergraph import Ubergraph


@lru_cache(maxsize=1)
def _table() -> dict[str, Any]:
    raw = resources.files("ontomap.data").joinpath("ehdaa2.json").read_text(encoding="utf-8")
    return json.loads(raw)


def terms() -> dict[str, dict[str, Any]]:
    return _table()["terms"]


def data_version() -> str | None:
    return _table()["data_version"]


@dataclass
class Window:
    """When a structure exists, in days post-fertilization. Either end may be open."""

    uberon_id: str
    ehdaa2_id: str
    ehdaa2_name: str | None
    starts_at: str | None          # HsapDv term id
    starts_at_label: str | None
    ends_at: str | None
    ends_at_label: str | None
    start_dpf: float | None
    end_dpf: float | None

    def covers(self, day_start: float, day_end: float | None = None) -> bool | None:
        """Does this structure exist across the sample's days?

        Returns ``None`` when the window is too open to say, and that is not the
        same as ``False``. Absence of a bound is absence of evidence; treating it
        as a negative would reject correct precursors for every term EHDAA2
        never closed.
        """
        end = day_start if day_end is None else day_end
        if self.start_dpf is not None and end < self.start_dpf:
            return False        # the sample predates the structure
        if self.end_dpf is not None and day_start > self.end_dpf:
            return False        # the structure is gone by then
        if self.start_dpf is None and self.end_dpf is None:
            return None
        return True

    def to_dict(self) -> dict[str, Any]:
        return {
            "uberon_id": self.uberon_id,
            "ehdaa2_id": self.ehdaa2_id,
            "ehdaa2_name": self.ehdaa2_name,
            "starts_at": self.starts_at,
            "starts_at_label": self.starts_at_label,
            "ends_at": self.ends_at,
            "ends_at_label": self.ends_at_label,
            "start_dpf": self.start_dpf,
            "end_dpf": self.end_dpf,
        }


def _dpf(hsapdv_id: str | None, which: str) -> float | None:
    if not hsapdv_id:
        return None
    return stage_table().get(hsapdv_id, {}).get(which)


def _label(hsapdv_id: str | None) -> str | None:
    if not hsapdv_id:
        return None
    return stage_table().get(hsapdv_id, {}).get("label")


def windows(uberon_ids: list[str], ubergraph: Ubergraph) -> dict[str, list[Window]]:
    """Stage windows for UBERON terms, via their EHDAA2 xrefs.

    A UBERON term may carry several EHDAA2 xrefs; all are returned rather than
    one picked, because disagreement between them is worth seeing.
    """
    if not uberon_ids:
        return {}
    xrefs = ubergraph.xrefs(uberon_ids, source="EHDAA2")
    table = terms()
    out: dict[str, list[Window]] = {}
    for uberon_id, refs in xrefs.items():
        found = []
        for ref in refs:
            entry = table.get(ref)
            if entry is None:
                continue
            starts, ends = entry.get("starts_at"), entry.get("ends_at")
            found.append(
                Window(
                    uberon_id=uberon_id,
                    ehdaa2_id=ref,
                    ehdaa2_name=entry.get("name"),
                    starts_at=starts,
                    starts_at_label=_label(starts),
                    ends_at=ends,
                    ends_at_label=_label(ends),
                    start_dpf=_dpf(starts, "start_dpf"),
                    # The *end* of the ending stage: the structure persists
                    # through the stage it ends at, not up to that stage's start.
                    end_dpf=_dpf(ends, "end_dpf"),
                )
            )
        out[uberon_id] = found
    return out


@lru_cache(maxsize=1)
def _reverse_xref_query() -> str:
    return """
SELECT ?s ?x WHERE {
  GRAPH <http://reasoner.renci.org/ontology> {
    ?s <http://www.geneontology.org/formats/oboInOwl#hasDbXref> ?x
  }
  FILTER(STRSTARTS(STR(?s), "http://purl.obolibrary.org/obo/UBERON_"))
  FILTER(STRSTARTS(STR(?x), "EHDAA2:"))
}"""


def reverse_index(ubergraph: Ubergraph) -> dict[str, list[str]]:
    """EHDAA2 id -> the UBERON terms that xref it. One query, cached."""
    from .ubergraph import curie

    rows = ubergraph.query(_reverse_xref_query())
    out: dict[str, list[str]] = {}
    for row in rows:
        out.setdefault(row["x"], []).append(curie(row["s"]))
    return out


def precursors(uberon_ids: list[str], ubergraph: Ubergraph) -> dict[str, list[dict[str, Any]]]:
    """EHDAA2's own ``develops_from``, mapped back onto UBERON.

    A second, human-specific precursor source independent of UBERON's
    ``RO:0002202``. Agreement between the two is evidence; a precursor found by
    one and not the other is a case for a dossier rather than a silent pick --
    which is the shape of §9.15, where "45 of 63 organs have no developmental
    variant" turned out to mean "no lexical match under these patterns".
    """
    if not uberon_ids:
        return {}
    xrefs = ubergraph.xrefs(uberon_ids, source="EHDAA2")
    table = terms()
    back = reverse_index(ubergraph)
    wanted: set[str] = set()
    per_term: dict[str, list[str]] = {}
    for uberon_id, refs in xrefs.items():
        found = [p for ref in refs for p in table.get(ref, {}).get("develops_from", [])]
        per_term[uberon_id] = found
        wanted.update(found)
    uberon_labels = ubergraph.labels(sorted({u for p in wanted for u in back.get(p, [])}))
    out: dict[str, list[dict[str, Any]]] = {}
    for uberon_id, found in per_term.items():
        rows = []
        for precursor in found:
            entry = table.get(precursor, {})
            for mapped in back.get(precursor, []) or [None]:
                rows.append(
                    {
                        "ehdaa2_id": precursor,
                        "ehdaa2_name": entry.get("name"),
                        "uberon_id": mapped,
                        "uberon_label": uberon_labels.get(mapped) if mapped else None,
                        "source": "ehdaa2",
                    }
                )
        out[uberon_id] = rows
    return out
