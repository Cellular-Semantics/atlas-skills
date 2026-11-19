"""The plugin's smoke cases: generated in step with the gold set, and graded
the way they claim. Free and offline: the patterns are run here against
hand-made picks.json files, not against an agent."""
from __future__ import annotations

import json
import re

import pytest
from obs_column_eval.manifest import subset, with_ground_truth
from smoke_cases import CASES, OUT, PORTAL, render

PROFILES = OUT.parents[3] / "evals" / "fixtures" / "profiles"


def _regex_graders(case: str) -> list[tuple[str, str, bool]]:
    """(name, pattern, must_match) for each regex grader of a case."""
    out = []
    for path in sorted((OUT / case / "graders").glob("*.md")):
        head = path.read_text().split("---")[1]
        if "type: regex" not in head:
            continue
        pattern = json.loads(re.search(r"^pattern: (.*)$", head, re.M).group(1))
        out.append((path.stem, pattern, "match: not_contains" not in head))
    return out


def _picks_json(cols: list[str]) -> str:
    return json.dumps({"schema_version": 1, "source": "obs.parquet", "dataset": "x",
                       "requested": ["cell_type"], "picks": {"cell_type": cols},
                       "reasoning": {"author-celltype-picker": "r"}}, indent=2)


def _failed(case: str, cols: list[str]) -> list[str]:
    text = _picks_json(cols)
    return [name for name, pattern, must in _regex_graders(case)
            if bool(re.search(pattern, text)) != must]


def test_smoke_cases_are_up_to_date():
    """Regenerate with `python3 evals/smoke_cases.py` after a gold or subset change."""
    stale = [p for p, text in render().items() if not p.exists() or p.read_text() != text]
    assert not stale, f"out of date: {[str(p) for p in stale]}"


def test_one_case_per_light_set_dataset():
    assert set(CASES) == set(subset())
    assert len({name for name, _ in CASES.values()}) == len(CASES)


def test_every_trap_is_a_real_obs_column_and_not_gold():
    truth = with_ground_truth(subset())
    for dsid, (_, traps) in CASES.items():
        profile = (PROFILES / f"{dsid}.txt").read_text()
        columns = {line.split(" | ", 1)[0] for line in profile.splitlines() if " | " in line}
        for col in traps:
            assert col in columns, f"{dsid}: trap {col} is not in obs"
            assert col not in truth[dsid]["curated"], f"{dsid}: trap {col} is gold"


@pytest.mark.parametrize("dsid", sorted(CASES))
def test_the_curated_answer_passes_every_grader(dsid):
    gold = with_ground_truth(subset())[dsid]["curated"]
    assert _failed(CASES[dsid][0], list(gold)) == []
    # order does not matter
    assert _failed(CASES[dsid][0], list(reversed(gold))) == []


@pytest.mark.parametrize("dsid", sorted(CASES))
def test_a_wrong_answer_fails(dsid):
    name, traps = CASES[dsid]
    gold = list(with_ground_truth(subset())[dsid]["curated"])
    # an extra portal pick fails its own grader and the exact count
    assert set(_failed(name, [*gold, PORTAL[0]])) >= {"exact-count", "not-portal-cell-type"}
    for trap in traps:
        assert f"not-{re.sub(r'[^a-z0-9]+', '-', trap.lower()).strip('-')}" in \
            _failed(name, [*gold, trap])
    if gold:
        # a missed column fails its own grader and the exact count
        missed = _failed(name, gold[1:])
        assert "exact-count" in missed and len(missed) == 2


def test_requested_cell_type_is_not_mistaken_for_the_picks():
    """`"requested": ["cell_type"]` must not satisfy the picks patterns."""
    assert "exact-count" in _failed("smoke-constant-columns", ["Lineage"])
    assert _failed("smoke-constant-columns", []) == []
