"""Running the fields in the order their dependencies require.

The ordering is enforced here, in code, rather than written down somewhere and
remembered. Species decides which stage ontology applies; stage, sex and disease
are all inputs to tissue; and tissue is therefore last. Getting this wrong does
not throw -- it silently produces a mature organ term for an embryo, or a
sex-neutral term for a female-only library, which is the kind of wrong that
validates.
"""

from __future__ import annotations

from typing import Any

from . import disease as disease_field
from . import sex as sex_field
from . import species as species_field
from . import stage as stage_field
from . import tissue as tissue_field
from .config import Config
from .index import LexicalIndex
from .ladder import Match
from .ols import Ols
from .reconcile import Reconciled, reconcile
from .ubergraph import Ubergraph

# The order is the dependency graph, flattened. Do not sort this list.
FIELD_ORDER = ("species", "sex", "stage", "disease", "tissue")


def map_record(
    record: dict[str, Any],
    config: Config,
    *,
    ubergraph: Ubergraph,
    indexes: dict[str, LexicalIndex],
    ols: Ols | None = None,
) -> dict[str, Any]:
    """Map every declared field of one extracted record, in dependency order."""
    mapped: dict[str, Any] = {}
    for name in FIELD_ORDER:
        sources = record["raw"].get(name)
        if not sources:
            continue
        if name == "tissue":
            mapped[name] = _map_tissue(record, mapped, config, ubergraph, indexes)
        else:
            mapped[name] = _map_simple(name, sources, config, ubergraph, indexes)
    return {**record, "mapped": mapped}


def _map_simple(
    name: str,
    sources: list[dict[str, Any]],
    config: Config,
    ubergraph: Ubergraph,
    indexes: dict[str, LexicalIndex],
) -> dict[str, Any]:
    per_column: dict[str, Match] = {}
    extras: dict[str, Any] = {}
    for source in sources:
        value = source["value"]
        if name == "species":
            per_column[source["column"]] = species_field.resolve(value)
        elif name == "sex":
            per_column[source["column"]] = sex_field.resolve(value)
        elif name == "disease":
            per_column[source["column"]] = disease_field.resolve(value, indexes["MONDO"])
        elif name == "stage":
            parsed = stage_field.parse(
                value,
                unit=source.get("unit"),
                frame=source.get("frame"),
                boundary=config.boundary,
            )
            extras[source["column"]] = parsed.to_dict()
            per_column[source["column"]] = Match(
                raw=parsed.raw,
                term_id=parsed.term_id,
                term_name=parsed.term_name,
                rule=parsed.rule,
                match_type=parsed.match_type,
                candidates=parsed.candidates,
                rationale=parsed.rationale,
                needs_review=parsed.needs_review,
                flags=parsed.flags,
            )
    combined: Reconciled = reconcile(per_column, ubergraph)
    result = combined.to_dict()
    if extras:
        result["stage_detail"] = extras
        # Carry the day window forward as a first-class value: tissue tests the
        # anatomy against exactly this number. It must come from the column that
        # won reconciliation -- taking the first column with any dpf at all
        # silently pairs one column's age with another column's stage term.
        chosen = extras.get(combined.winner or "")
        if chosen is None:
            chosen = next((d for d in extras.values() if d.get("dpf_start") is not None), None)
        if chosen is not None:
            result["dpf_start"] = chosen.get("dpf_start")
            result["dpf_end"] = chosen.get("dpf_end")
    return result


def _map_tissue(
    record: dict[str, Any],
    mapped: dict[str, Any],
    config: Config,
    ubergraph: Ubergraph,
    indexes: dict[str, LexicalIndex],
) -> dict[str, Any]:
    stage_result = mapped.get("stage", {})
    sex_result = mapped.get("sex", {})
    disease_result = mapped.get("disease", {})
    species_result = mapped.get("species", {})

    context = tissue_field.Context(
        taxon=species_result.get("term_id"),
        dpf_start=stage_result.get("dpf_start"),
        dpf_end=stage_result.get("dpf_end"),
        sex_term=sex_result.get("term_id"),
        # Reads the flag, not the empty mapped field. A pooled library maps to
        # no PATO term, so a guard reading the term sees "absent" for exactly
        # the rows that most need blocking.
        sex_mixed="sex_mixed" in (sex_result.get("flags") or []),
        disease_term=disease_result.get("term_id"),
        disease_raw=disease_result.get("raw"),
    )

    per_column: dict[str, Match] = {}
    details: dict[str, Any] = {}
    for source in record["raw"]["tissue"]:
        result = tissue_field.resolve(source["value"], indexes["UBERON"], ubergraph, context)
        per_column[source["column"]] = result.match
        details[source["column"]] = result.to_dict()

    combined = reconcile(per_column, ubergraph)
    winner_column = next(
        (c for c, m in per_column.items() if m is combined.match), next(iter(per_column))
    )
    out = {**details[winner_column], **combined.to_dict()}
    out["context"] = {
        "dpf_start": context.dpf_start,
        "dpf_end": context.dpf_end,
        "sex_term": context.sex_term,
        "sex_mixed": context.sex_mixed,
        "disease_term": context.disease_term,
    }
    out["per_column"] = details
    return out


def row_status(mapped: dict[str, Any], scope: str) -> str:
    if scope != "in_scope":
        return "out_of_scope"
    for result in mapped.values():
        if result.get("needs_review") or result.get("agreement") == "conflict":
            return "needs_review"
    return "complete"
