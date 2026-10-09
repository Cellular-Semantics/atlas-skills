"""Tests for the ontology-mapping scorer.

The scorer is the thing that decides whether a run passed, so a bug here is
invisible and expensive: it either passes a bad run or fails a good one, and
neither announces itself. These pin the rules that replaced the old `rung`
integer.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

import check  # noqa: E402
from moves import MOVES  # noqa: E402

GOOD = {
    "id": "x",
    "curie": "UBERON:0001225",
    "label": "cortex of kidney",
    "moves_used": ["exact"],
    "answered_by": "exact",
    "why_this_not_that": "kidney in the record rules out the generic grouping class",
    "rejected": [{"curie": "UBERON:0001851", "reason": "grouping class"}],
}
CASE = {"id": "x", "accepted": ["UBERON:0001225"]}


def run(case_extra=None, report_extra=None):
    case = {**CASE, **(case_extra or {})}
    report = {**GOOD, **(report_extra or {})}
    return check.check(case, report)


def test_a_good_report_passes():
    ok, problems = run()
    assert ok, problems
    assert problems == []


def test_wrong_term_fails():
    ok, problems = run(report_extra={"curie": "UBERON:0001851"})
    assert not ok
    assert "accepted are" in problems[0]


def test_must_not_answer_is_reported_even_when_accepted_is_silent():
    """The cortex trap: the point of the case is the term it must not pick."""
    ok, problems = run(
        case_extra={"accepted": ["UBERON:0001225", "UBERON:0001851"],
                    "must_not_answer": ["UBERON:0001851"]},
        report_extra={"curie": "UBERON:0001851"},
    )
    assert not ok
    assert any("exists to rule out" in p for p in problems)


def test_a_move_the_case_requires_must_appear():
    ok, problems = run(case_extra={"must_use": ["region"]})
    assert not ok
    assert any("never used ['region']" in p for p in problems)


def test_a_forbidden_move_is_a_failure_of_proportion():
    """trivial-exact exists to catch effort, not error: the term can be right
    and the run still fail."""
    ok, problems = run(
        case_extra={"must_not_use": ["common-ancestors"]},
        report_extra={"moves_used": ["exact", "common-ancestors"]},
    )
    assert not ok
    assert any("failure of proportion" in p for p in problems)


def test_too_many_moves_fails_even_with_the_right_answer():
    ok, problems = run(
        case_extra={"max_moves": 1},
        report_extra={"moves_used": ["exact", "stemmed", "alt-names"]},
    )
    assert not ok
    assert any("at most 1" in p for p in problems)


def test_answered_by_must_be_among_the_moves_used():
    """Catches a report that claims a route it never says it took."""
    ok, problems = run(report_extra={"answered_by": "region"})
    assert not ok
    assert any("not among moves_used" in p for p in problems)


def test_an_unknown_move_name_is_fatal_not_ignored():
    """Drift between the skill's section headings and the eval vocabulary is
    silent otherwise, and shows up as a case that can never pass."""
    ok, problems = run(report_extra={"moves_used": ["lexical"], "answered_by": "lexical"})
    assert not ok
    assert any("unknown move" in p for p in problems)


def test_missing_moves_is_soft_not_fatal():
    """An old-style report should warn rather than crash the whole run."""
    report = {k: v for k, v in GOOD.items() if k != "moves_used"}
    report.pop("answered_by")
    ok, problems = check.check(CASE, report)
    assert ok
    assert any(p.startswith("~no moves_used") for p in problems)


def test_no_why_this_not_that_fails():
    ok, problems = run(report_extra={"why_this_not_that": "  "})
    assert not ok
    assert any("exit test was not met" in p for p in problems)


def test_unresolved_expected_and_given():
    ok, problems = check.check(
        {"id": "x", "accepted": [], "expect_unresolved": True},
        {**GOOD, "curie": None, "unresolved": True},
    )
    assert ok, problems


def test_unresolved_expected_but_answered():
    ok, problems = check.check({"id": "x", "accepted": [], "expect_unresolved": True}, GOOD)
    assert not ok
    assert any("expected answer is unresolved" in p for p in problems)


def test_must_mention_searches_every_part_of_the_report():
    """Including the fields that only exist to record what went wrong --
    ehdaa2-outside-ubergraph passes by saying so in `unavailable`."""
    ok, problems = run(
        case_extra={"must_mention": ["Ubergraph"]},
        report_extra={"unavailable": ["common-ancestors: ehdaa2 is not in Ubergraph"]},
    )
    assert ok, problems


@pytest.mark.parametrize("case", json.loads((ROOT / "cases-core.json").read_text())["cases"])
def test_every_shipped_case_is_well_formed(case):
    assert not check.validate_cases([case])


def test_shipped_cases_only_name_known_moves():
    cases = json.loads((ROOT / "cases-core.json").read_text())["cases"]
    named = {m for c in cases for k in ("must_use", "must_not_use", "answered_by_any_of")
             for m in c.get(k) or []}
    assert named <= set(MOVES)
