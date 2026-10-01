"""Scoring against a gold set, per rule path -- never as one number.

An aggregate score hides everything that matters. A run once scored 15/15 on
stage and 8/8 on tissue while `skin` was mapped to `pedal digit skin`: every
gold tissue string happened to hit an exact label, so the fuzzy path was never
exercised and the aggregate was both true and useless. A human reading the
output table found the bug.

So: accuracy is reported per rule, paths with no gold coverage are named as
unevaluated rather than omitted, and no aggregate is emitted without the
breakdown beside it.

Deliberate refusals are counted separately and are not errors. A rising refusal
count after a fix is a good sign, and coverage falling because false mappings
were withdrawn is progress. Reported as such, because otherwise the next person
to look at the numbers will "fix" it.
"""

from __future__ import annotations

from typing import Any


def compare(
    records: list[dict[str, Any]],
    gold: dict[int, dict[str, str]],
    *,
    field: str,
    gold_complete: bool = True,
) -> dict[str, Any]:
    """Compare mapped terms against curator-assigned ids, split by rule path."""
    by_rule: dict[str, dict[str, Any]] = {}
    unscored = {"not_in_gold": 0, "out_of_scope": 0, "refused": 0}

    for record in records:
        result = (record.get("mapped") or {}).get(field)
        if result is None:
            continue
        rule = result.get("rule") or "unmatched"
        bucket = by_rule.setdefault(
            rule, {"correct": 0, "wrong": 0, "refused": 0, "unscored": 0, "examples": []}
        )

        if record.get("scope") != "in_scope":
            unscored["out_of_scope"] += 1
            bucket["unscored"] += 1
            continue

        expected = (gold.get(record.get("row")) or {}).get(field)
        if not expected:
            unscored["not_in_gold"] += 1
            bucket["unscored"] += 1
            continue

        actual = result.get("term_id")
        if actual is None:
            unscored["refused"] += 1
            bucket["refused"] += 1
            continue

        if actual == expected:
            bucket["correct"] += 1
        else:
            bucket["wrong"] += 1
            if len(bucket["examples"]) < 5:
                bucket["examples"].append(
                    {"raw": result.get("raw"), "got": actual, "expected": expected}
                )

    scored = sum(b["correct"] + b["wrong"] for b in by_rule.values())
    correct = sum(b["correct"] for b in by_rule.values())

    return {
        "field": field,
        "gold_complete": gold_complete,
        "scored": scored,
        "correct": correct,
        # Deliberately not a headline. It is only meaningful read next to
        # per-rule coverage, and this key name says so.
        "aggregate_accuracy_read_with_per_rule": round(correct / scored, 4) if scored else None,
        "per_rule": {
            rule: {
                **counts,
                "accuracy": (
                    round(counts["correct"] / (counts["correct"] + counts["wrong"]), 4)
                    if counts["correct"] + counts["wrong"]
                    else None
                ),
                "evaluated": bool(counts["correct"] + counts["wrong"]),
            }
            for rule, counts in sorted(by_rule.items())
        },
        "unevaluated_paths": sorted(
            rule for rule, c in by_rule.items() if not (c["correct"] + c["wrong"])
        ),
        "unscored": unscored,
        "note": (
            "Paths listed in unevaluated_paths were exercised but the gold set says "
            "nothing about them: they are untested, not passing. "
            + (
                ""
                if gold_complete
                else "The gold set is declared incomplete, so 'not_in_gold' is not 'wrong'."
            )
        ),
    }


def coverage(records: list[dict[str, Any]], *, field: str) -> dict[str, Any]:
    """Coverage split by scope and match type. Three different claims, three numbers."""
    counts: dict[str, dict[str, int]] = {}
    for record in records:
        result = (record.get("mapped") or {}).get(field)
        if result is None:
            continue
        scope = record.get("scope", "in_scope")
        bucket = counts.setdefault(scope, {})
        key = result.get("match_type") or ("refused" if not result.get("term_id") else "assigned")
        bucket[key] = bucket.get(key, 0) + 1
    return {"field": field, "by_scope_and_match_type": counts}
