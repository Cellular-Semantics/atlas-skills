"""The metrics. Pure arithmetic, so these are fast and offline."""
from __future__ import annotations

import pytest
from obs_column_eval import (
    bootstrap_ci,
    hypergeom_p_hit,
    jaccard,
    score_by_tier,
    score_picks,
    summarise,
    wilson,
)


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


# --- tiers -------------------------------------------------------------------

def _rows(scores: dict[str, float]) -> list[dict]:
    return [{"dsid": d, "jaccard": j, "precision": j, "recall": j, "hit": int(j > 0)}
            for d, j in scores.items()]


MANIFEST = {
    "a1": {"tier": "n73", "group": "Gut", "cxg_dataset_ids": ["A"]},
    "a2": {"tier": "n73", "group": "Gut", "cxg_dataset_ids": ["A"]},  # same dataset
    "b": {"tier": "n73", "group": "Lung", "cxg_dataset_ids": ["B"]},
    "c": {"tier": "l4", "group": "Retina", "cxg_dataset_ids": ["C"]},
}


def test_each_tier_is_scored_as_listed():
    out = score_by_tier(_rows({"a1": 1.0, "a2": 0.0, "b": 1.0, "c": 0.5}), MANIFEST)
    assert out["tiers"]["n73"]["n"] == 3
    assert out["tiers"]["n73"]["jaccard"]["mean"] == pytest.approx(2 / 3)
    assert out["tiers"]["l4"]["n"] == 1


def test_combined_figure_counts_a_dataset_once():
    """Two versions of one CELLxGENE dataset weigh once in `all`, averaged,
    and are a hit only if both were."""
    out = score_by_tier(_rows({"a1": 1.0, "a2": 0.0, "b": 1.0, "c": 0.5}), MANIFEST)
    both = out["all"]
    assert both["n"] == 3 and both["n_entries"] == 4
    assert both["jaccard"]["mean"] == pytest.approx((0.5 + 1.0 + 0.5) / 3)
    assert both["hit_rate"]["k"] == 2


def test_tier_scoring_reports_groups_and_strays():
    out = score_by_tier(_rows({"c": 0.5, "zzz": 1.0}), MANIFEST)
    assert out["by_group"]["l4"] == {"Retina": {"n": 1, "jaccard": 0.5}}
    assert out["outside_test_set"] == ["zzz"]
    assert "zzz" not in str(out["tiers"])


def test_summarise_matches_score_picks():
    scored = score_picks({"x": ["a"], "y": ["b", "c"]},
                         {"x": {"columns": ["a"]}, "y": {"columns": ["b"]}})
    assert summarise(scored["per_dataset"]) == scored["overall"]
