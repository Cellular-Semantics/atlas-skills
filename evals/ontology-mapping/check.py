#!/usr/bin/env python3
"""Score an eval run against evals/cases.json.

    python evals/check.py evals/runs/<name>.json

A run file is a JSON list of the skill's reports, one per case:

    [ { "id": "cornea-conjunctiva",
        "curie": "UBERON:0010409",
        "label": "ocular surface region",
        "rung": 3,
        "why_this_not_that": "...",
        "rejected": [{"curie": "UBERON:0000019", "reason": "..."}],
        "unresolved": false,
        "notes": "..." } ]

What this checks is only what can be checked mechanically: the term, the
proportion of effort, whether a rival was named, and whether the report says the
things a particular case exists to elicit. Whether the *reasoning* was any good
is a human read of `why_this_not_that`, and the script says so rather than
pretending otherwise.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).parent
CASES = ROOT / "cases-core.json"


def _text(report: dict) -> str:
    """Everything the report said, lowercased, for the mention checks."""
    parts = [
        str(report.get("why_this_not_that") or ""),
        str(report.get("notes") or ""),
        str(report.get("label") or ""),
    ]
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

    # --- proportion of effort
    rung = report.get("rung")
    if rung is None:
        problems.append("~no rung reported")
    else:
        if (cap := case.get("max_rung")) is not None and rung > cap:
            problems.append(f"reached rung {rung}; this should finish by rung {cap}")
        elif (exp := case.get("expected_rung")) is not None and rung != exp:
            problems.append(f"~exited at rung {rung}, expected {exp}")

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


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__)
        return 64
    cases = json.loads(CASES.read_text())["cases"]
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
        print(f"[ ?  ] {e}: in the run but not in cases.json")

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
