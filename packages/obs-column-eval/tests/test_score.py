"""The metrics. Pure arithmetic, so these are fast and offline."""
from __future__ import annotations

import pytest
from obs_column_eval import bootstrap_ci, hypergeom_p_hit, jaccard, score_picks, wilson


def test_jaccard():
    assert jaccard([], []) == 1.0          # nothing curated, nothing picked: agreement
    assert jaccard(["a"], []) == 0.0
    assert jaccard(["a", "b"], ["b", "c"]) == 1 / 3
    assert jaccard(["a"], ["a"]) == 1.0


def test_wilson_interval_brackets_the_point_estimate():
    lo, hi = wilson(72, 73)
    assert lo < 72 / 73 < hi
    assert 0.92 < lo < 0.95


def test_wilson_on_no_trials_does_not_divide_by_zero():
    assert wilson(0, 0) == (0.0, 0.0)


def test_bootstrap_ci_is_seeded():
    values = [0.5, 0.6, 0.7, 0.8, 0.9]
    assert bootstrap_ci(values, B=500, seed=0) == bootstrap_ci(values, B=500, seed=0)
    lo, hi = bootstrap_ci(values, B=500, seed=0)
    assert 0 <= lo <= hi <= 1


@pytest.mark.parametrize(("n", "k", "picked", "expected"), [
    (40, 0, 3, 0.0),     # nothing to hit
    (40, 3, 0, 0.0),     # nothing picked
    (40, 3, 40, 1.0),    # picked everything
])
def test_hypergeom_null(n, k, picked, expected):
    assert hypergeom_p_hit(N=n, K=k, k=picked) == expected


def test_score_picks_per_dataset():
    out = score_picks({"d1": ["A", "B"], "d2": ["X"]},
                      {"d1": {"columns": ["A", "C"]}, "d2": {"columns": ["X", "Y"]}})
    assert out["overall"]["n"] == 2
    d1 = next(r for r in out["per_dataset"] if r["dsid"] == "d1")
    assert (d1["jaccard"], d1["precision"], d1["recall"], d1["hit"]) == (1 / 3, 0.5, 0.5, 1)
    assert d1["missed_by_agent"] == ["C"]
    assert d1["agent_extras"] == ["B"]


def test_picking_nothing_when_there_is_nothing_is_a_hit():
    """A dataset whose author columns are all constant has no cell-type field.
    Picking nothing is the right answer and must not be scored as a miss."""
    out = score_picks({"d": []}, {"d": {"columns": []}})
    row = out["per_dataset"][0]
    assert row["hit"] == 1
    assert row["jaccard"] == row["precision"] == row["recall"] == 1.0


def test_picking_something_when_there_is_nothing_is_a_miss():
    out = score_picks({"d": ["Lineage"]}, {"d": {"columns": []}})
    row = out["per_dataset"][0]
    assert row["hit"] == 0
    assert row["precision"] == 0.0


def test_null_model_needs_the_schema_size():
    picks = {"d": ["A"]}
    curation = {"d": {"columns": ["A", "B"]}}
    assert "null_hit_p" not in score_picks(picks, curation)["per_dataset"][0]
    with_schema = score_picks(picks, curation, schema={"d": dict.fromkeys("ABCDEFGH")})
    row = with_schema["per_dataset"][0]
    assert row["n_obs_cols"] == 8
    assert 0 < row["null_hit_p"] < 1
    assert "null_hit_rate_expected" in with_schema["overall"]
