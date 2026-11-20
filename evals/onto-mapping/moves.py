"""The named moves a mapping report can say it used.

These are the section headings under Stage 2 (Find) in the skill, plus the
quantity route from Stage 1. They are a closed vocabulary on purpose: a report
that names a move not in this list, or a case that asks for one, is a typo or a
drift between the skill text and the eval, and either is worth failing on
rather than silently ignoring.

Keep in step with `plugins/onto-mapping/skills/map-to-ontology/SKILL.md`.
"""

from __future__ import annotations

MOVES = {
    "convert": "Stage 1: convert, construct, verify -- the route for a quantity",
    "exact": "the exact probe",
    "stemmed": "the stemmed probe",
    "alt-names": "names the ontology might actually use (word substitution)",
    "region": "search inside a region (cohort --under)",
    "common-ancestors": "common ancestors of a seed set",
    "relations": "parts and inhabitants of a structure",
    "outside-ubergraph": "neighbours, hierarchy, crosswalk, xrefs",
}


def unknown(names) -> list[str]:
    return sorted({n for n in names or [] if n not in MOVES})


def describe() -> str:
    return "\n".join(f"  {k:<18} {v}" for k, v in MOVES.items())
