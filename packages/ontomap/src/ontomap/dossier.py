"""The judgement interface: what an agent reads instead of browsing an ontology.

A dossier is assembled by code, per unresolved string, and it is the only thing
the judging agent sees. That constraint is the point. An agent that browses can
find a term it likes and write the id from memory; an agent given a dossier can
only choose among ids that are present in it, and the id it chose can be checked
against the same file weeks later.

What goes in is what settles calls in practice:

- every candidate's **definition**, which decides most of them;
- its **is_a parents** and **part_of targets**, so its place is visible;
- **stage windows**, where the anatomy has one;
- **targeted lookups** of terms a knowledgeable curator would think to check and
  lexical retrieval did not surface;
- **sample counts**, so effort follows the cells.
"""

from __future__ import annotations

from typing import Any

from . import ehdaa2
from .index import LexicalIndex
from .ols import Ols
from .stage import terms_covering
from .ubergraph import PART_OF, SUBCLASS_OF, Ubergraph


def build(
    field: str,
    value: str,
    result: dict[str, Any],
    *,
    count: int,
    ubergraph: Ubergraph,
    index: LexicalIndex | None = None,
    ols: Ols | None = None,
    ontology: str = "UBERON",
) -> dict[str, Any]:
    """Assemble one dossier. Everything in it comes from a cached API response."""
    candidates = list(result.get("candidates") or [])

    # Lexical retrieval, for candidates only. Nothing from here may be assigned,
    # and the dossier says so in the field name rather than relying on the agent
    # remembering the rule.
    if ols is not None:
        seen = {c.get("id") for c in candidates}
        for found in ols.search(value, ontology=ontology, rows=8):
            if found["id"] not in seen:
                candidates.append({**found, "assignable": False})

    ids = [c["id"] for c in candidates if c.get("id")]
    detail = ubergraph.term_detail(ids) if ids else {}
    parents = ubergraph.ancestors(ids, via=(SUBCLASS_OF,), graph="http://reasoner.renci.org/nonredundant") if ids else {}
    part_of = ubergraph.ancestors(ids, via=(PART_OF,), graph="http://reasoner.renci.org/nonredundant") if ids else {}
    labels = ubergraph.labels(sorted({p for s in (*parents.values(), *part_of.values()) for p in s})) if ids else {}

    enriched = []
    for candidate in candidates:
        term_id = candidate.get("id")
        info = detail.get(term_id, {})
        enriched.append(
            {
                **candidate,
                "label": candidate.get("label") or info.get("label"),
                "definition": candidate.get("definition") or info.get("definition"),
                "comment": info.get("comment"),
                "synonyms": info.get("synonyms", []),
                "is_a_parents": [
                    {"id": p, "label": labels.get(p)} for p in sorted(parents.get(term_id, []))
                ],
                "part_of": [
                    {"id": p, "label": labels.get(p)} for p in sorted(part_of.get(term_id, []))
                ],
                "information_content": info.get("information_content"),
                "obsolete": info.get("deprecated", False),
            }
        )

    dossier: dict[str, Any] = {
        "field": field,
        "raw_value": value,
        "sample_count": count,
        "rule_outcome": {
            "rule": result.get("rule"),
            "term_id": result.get("term_id"),
            "rationale": result.get("rationale"),
            "flags": result.get("flags", []),
        },
        "candidates": enriched,
        "instructions": _INSTRUCTIONS,
    }

    if field == "tissue":
        dossier["anatomy_notes"] = _tissue_notes(result, enriched, ubergraph)
    if field == "stage":
        dossier["stage_notes"] = _stage_notes(result)
    return dossier


def _tissue_notes(
    result: dict[str, Any], candidates: list[dict[str, Any]], ubergraph: Ubergraph
) -> dict[str, Any]:
    notes: dict[str, Any] = {}
    evidence = result.get("evidence") or {}
    if evidence.get("parts"):
        notes["decomposition"] = evidence["parts"]
    if evidence.get("rejected_ancestors"):
        notes["rejected_common_ancestors"] = evidence["rejected_ancestors"]
    if result.get("context", {}).get("dpf_start") is not None:
        ids = [c["id"] for c in candidates if c.get("id", "").startswith("UBERON:")]
        windows = ehdaa2.windows(ids, ubergraph) if ids else {}
        dpf_start = result["context"]["dpf_start"]
        dpf_end = result["context"].get("dpf_end")
        notes["stage_windows"] = {
            term_id: [
                {**w.to_dict(), "covers_sample": w.covers(dpf_start, dpf_end)}
                for w in found
            ]
            for term_id, found in windows.items()
            if found
        }
        notes["sample_dpf"] = [dpf_start, dpf_end]
        notes["reading_stage_windows"] = (
            "covers_sample: true means the structure exists at the sample's age; false "
            "rules the term out; null means EHDAA2 left the window open at that end, "
            "which is absence of evidence and not evidence of absence."
        )
    return notes


def _stage_notes(result: dict[str, Any]) -> dict[str, Any]:
    notes: dict[str, Any] = {
        "canonical": result.get("canonical"),
        "frame": result.get("frame"),
        "dpf": [result.get("dpf_start"), result.get("dpf_end")],
    }
    if result.get("dpf_start") is not None:
        notes["all_terms_covering_these_days"] = terms_covering(
            result["dpf_start"], result.get("dpf_end"), granular_only=False
        )
    notes["frames_differ_by_two_weeks"] = (
        "Gestational age counts from the last menstrual period, post-fertilization age "
        "from conception. HsapDv week terms are post-fertilization. A study may write "
        "'gestational' and report post-conception weeks, so the frame is a per-study "
        "question to settle from the paper, not a per-string one."
    )
    return notes


_INSTRUCTIONS = (
    "Assign a term only if a definition or axiom in this dossier supports it. Quote that "
    "text as `basis`, separately from your `rationale`. Do not write an id that does not "
    "appear in this dossier, and do not write one from memory: every id is re-checked "
    "against the live ontology afterwards, and an invented one fails. Candidates marked "
    "`assignable: false` came from lexical search and are there to be considered, not "
    "taken. Declining is a valid and expected outcome -- record the candidates you "
    "rejected and why none was defensible."
)
