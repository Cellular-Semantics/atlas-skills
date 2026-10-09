#!/usr/bin/env python3
"""Score an eval run against cases-core.json.

    python evals/ontology-mapping/check.py <run-file.json>

A run file is a JSON list of the skill's reports, one per case:

    [ { "id": "cornea-conjunctiva",
        "curie": "UBERON:0010409",
        "label": "ocular surface region",
        "moves_used": ["exact", "common-ancestors"],
        "answered_by": "common-ancestors",
        "why_this_not_that": "...",
        "rejected": [{"curie": "UBERON:0000019", "reason": "..."}],
        "unresolved": false,
        "unavailable": [], "validators_flagged": [], "unaccounted": [],
        "notes": "..." } ]

This replaces an earlier version that scored a single `rung` integer. The skill
no longer has rungs: Find is a menu of moves selected by the last failure
signal, not a staircase, so "how far up did it go" has no referent. What took
its place is richer and is what you want when debugging a failure six months
later -- *which* moves were used, and which one produced the answer. A case can
then say that a location query was the point, or that reaching for the graph at
all was a failure of proportion, neither of which a number could express.

What this checks is only what can be checked mechanically: the term, which
moves were used, whether a rival was named, and whether the report says the
things a particular case exists to elicit. Whether the *reasoning* was any good
is a human read of `why_this_not_that`, and the script says so rather than
pretending otherwise.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

from moves import MOVES, describe, unknown  # noqa: E402

CASES = ROOT / "cases-core.json"


def _text(report: dict) -> str:
    """Everything the report said, lowercased, for the mention checks."""
    parts = [
        str(report.get("why_this_not_that") or ""),
        str(report.get("notes") or ""),
        str(report.get("label") or ""),
    ]
    for key in ("unavailable", "validators_flagged", "unaccounted"):
        parts.extend(str(x) for x in report.get(key) or [])
    for r in report.get("rejected") or []:
        parts.append(str(r.get("reason") or ""))
        parts.append(str(r.get("label") or ""))
    return " ".join(parts).lower()


def check(case: dict, report: dict | None) -> tuple[bool, list[str]]:
    """Return (passed, problems). A problem that is not fatal is prefixed '~'."""
    if report is None:
        return False, ["no report for this case"]

    problems: list[str] = []
    curie = report.get("curie")
    unresolved = bool(report.get("unresolved")) or curie in (None, "", "unresolved")

    # --- the term itself
    if case.get("expect_unresolved"):
        if not unresolved:
            problems.append(f"answered {curie}; the expected answer is unresolved")
    elif unresolved:
        problems.append(f"unresolved; expected one of {case['accepted']}")
    elif curie not in case["accepted"]:
        problems.append(f"answered {curie}; accepted are {case['accepted']}")

    for bad in case.get("must_not_answer") or []:
        if curie == bad:
            problems.append(f"answered {bad}, which this case exists to rule out")

    # --- which moves were made
    used = report.get("moves_used")
    answered_by = report.get("answered_by")
    if used is None:
        problems.append("~no moves_used reported, so proportion cannot be judged")
        used = []
    if bad := unknown(used):
        problems.append(f"moves_used names unknown move(s) {bad}; known are {sorted(MOVES)}")
    if answered_by and unknown([answered_by]):
        problems.append(f"answered_by names unknown move {answered_by!r}")
    if answered_by and used and answered_by not in used:
        problems.append(f"answered_by {answered_by!r} is not among moves_used {used}")

    used_set = set(used)
    if missing := set(case.get("must_use") or []) - used_set:
        problems.append(f"never used {sorted(missing)}, which is the point of this case")
    if forbidden := set(case.get("must_not_use") or []) & used_set:
        problems.append(
            f"used {sorted(forbidden)}; this record should not need it, so reaching "
            "for it is a failure of proportion rather than of accuracy"
        )
    if (want := case.get("answered_by_any_of")) and answered_by not in want:
        problems.append(f"~answered by {answered_by!r}; expected one of {want}")
    if (cap := case.get("max_moves")) is not None and len(used_set) > cap:
        problems.append(
            f"used {len(used_set)} moves ({sorted(used_set)}); this record should "
            f"settle in at most {cap}"
        )

    # --- the exit test
    if not str(report.get("why_this_not_that") or "").strip():
        problems.append("no why-this-not-that line; the exit test was not met")

    rivals = {r.get("curie") for r in report.get("rejected") or []}
    if wanted := case.get("must_name_rival_from"):
        named = rivals & set(wanted) - {curie}
        if not named:
            problems.append(f"named no rival from {wanted}")
    elif not case.get("expect_unresolved") and not rivals:
        problems.append("~no rejected candidates reported, so there is no audit trail")

    # --- things the case exists to elicit
    text = _text(report)
    for phrase in case.get("must_mention") or []:
        if phrase.lower() not in text:
            problems.append(f"~report never mentions {phrase!r}")

    fatal = [p for p in problems if not p.startswith("~")]
    return not fatal, problems


def validate_cases(cases: list[dict]) -> list[str]:
    """Catch a case that asks for a move the skill does not have.

    A typo here is worse than a failing case: it fails every run for a reason
    that has nothing to do with the skill.
    """
    problems = []
    for c in cases:
        for key in ("must_use", "must_not_use", "answered_by_any_of"):
            if bad := unknown(c.get(key)):
                problems.append(f"{c['id']}: {key} names unknown move(s) {bad}")
        if c.get("expect_unresolved") and c.get("accepted"):
            problems.append(f"{c['id']}: expects unresolved but also lists accepted terms")
        if not c.get("expect_unresolved") and not c.get("accepted"):
            problems.append(f"{c['id']}: no accepted terms and does not expect unresolved")
    return problems


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__)
        print("moves a report may name:")
        print(describe())
        return 64
    cases = json.loads(CASES.read_text())["cases"]

    if broken := validate_cases(cases):
        print("the case file itself is wrong:")
        for p in broken:
            print(f"  {p}")
        return 2

    run = json.loads(Path(argv[1]).read_text())
    by_id = {r.get("id"): r for r in run}

    passed = soft = 0
    for case in cases:
        ok, problems = check(case, by_id.get(case["id"]))
        passed += ok
        soft += sum(1 for p in problems if p.startswith("~"))
        mark = "pass" if ok else "FAIL"
        print(f"[{mark}] {case['id']}")
        for p in problems:
            print(f"        {p}")

    extra = set(by_id) - {c["id"] for c in cases}
    for e in sorted(extra):
        print(f"[ ?  ] {e}: in the run but not in cases-core.json")

    print()
    print(f"{passed}/{len(cases)} passed, {soft} soft warning(s)")
    print(
        "Not checked here: whether the reasoning in why_this_not_that is sound, "
        "whether the rejections are the right ones, and whether the seed set for "
        "any common-ancestors call was sensibly partitioned. Read those."
    )
    return 0 if passed == len(cases) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
