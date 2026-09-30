"""Rules plus judgement into one worktable, with the two kept distinguishable.

Judgement wins where it exists. But a judgement row and a rule row carry
different warranties and must stay separable forever, so every row records who
produced it. Folding them into an indistinguishable table is how a curator's
considered call and a string match come to look like the same kind of fact.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any


def load_judgements(rows: list[dict[str, Any]]) -> dict[tuple[str, str], dict[str, Any]]:
    """Index judgement rows by (field, raw_value)."""
    return {(r["field"], r["raw_value"]): r for r in rows}


def fold(
    records: list[dict[str, Any]],
    judgements: dict[tuple[str, str], dict[str, Any]],
    *,
    curator: str = "rules",
) -> list[dict[str, Any]]:
    from .pipeline import row_status

    stamped = datetime.now(UTC).isoformat(timespec="seconds")
    out = []
    for record in records:
        mapped = {}
        for field_name, result in (record.get("mapped") or {}).items():
            judgement = judgements.get((field_name, result.get("raw", "")))
            if judgement and judgement.get("term_id"):
                mapped[field_name] = {
                    **result,
                    "term_id": judgement["term_id"],
                    "term_name": judgement.get("term_name"),
                    "match_type": judgement.get("match_type"),
                    "exemplar_specific_term_id": judgement.get("exemplar_specific_term_id"),
                    "specific_term_missing": judgement.get("specific_term_missing", False),
                    "basis": judgement.get("basis"),
                    "rationale": judgement.get("rationale"),
                    "rule": "judgement",
                    "curator": judgement.get("curator", "agent"),
                    "curated_at": judgement.get("curated_at", stamped),
                    "needs_review": False,
                    "rule_outcome": {
                        # What the rules said before judgement replaced it. Kept
                        # because a judgement that silently overrode a passing
                        # rule is the one case worth auditing.
                        "rule": result.get("rule"),
                        "term_id": result.get("term_id"),
                    },
                }
            elif judgement:
                mapped[field_name] = {
                    **result,
                    "curator": judgement.get("curator", "agent"),
                    "curated_at": judgement.get("curated_at", stamped),
                    "needs_review": True,
                    "declined_reason": judgement.get("rationale"),
                }
            else:
                mapped[field_name] = {**result, "curator": curator}
        out.append({**record, "mapped": mapped,
                    "row_status": row_status(mapped, record.get("scope", "in_scope"))})
    return out


def worktable(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Flatten to one row per sample with the documented output columns."""
    rows = []
    for record in records:
        row: dict[str, Any] = {
            "row": record.get("row"),
            "scope": record.get("scope"),
            "row_status": record.get("row_status"),
        }
        for field_name, result in (record.get("mapped") or {}).items():
            prefix = field_name
            row[f"raw_{prefix}"] = result.get("raw")
            row[f"{prefix}_term_name"] = result.get("term_name")
            row[f"{prefix}_term_id"] = result.get("term_id")
            row[f"{prefix}_rule"] = result.get("rule")
            row[f"{prefix}_match_type"] = result.get("match_type")
            row[f"{prefix}_basis"] = result.get("basis")
            row[f"{prefix}_rationale"] = result.get("rationale")
            row[f"{prefix}_needs_review"] = result.get("needs_review")
            row[f"{prefix}_curator"] = result.get("curator")
            row[f"{prefix}_agreement"] = result.get("agreement")
            row[f"{prefix}_other_candidates"] = "; ".join(
                f"{c.get('label')} ({c.get('id')})"
                for c in (result.get("candidates") or [])
                if c.get("id") and c.get("id") != result.get("term_id")
            )
            if field_name == "tissue":
                row["tissue_type"] = result.get("tissue_type")
                row["sampled_site_condition"] = result.get("sampled_site_condition")
                row["tissue_term_mature_id"] = result.get("term_mature_id")
                row["tissue_parts_free_text"] = result.get("parts_free_text")
                row["tissue_specific_term_missing"] = result.get("specific_term_missing")
        rows.append(row)
    return rows
