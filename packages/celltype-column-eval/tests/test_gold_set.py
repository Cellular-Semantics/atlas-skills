"""The gold set: the curation snapshot, the manifest, and the frozen baseline.

These are the things a score is only meaningful against. If the snapshot moves,
every published number moves with it, so its shape is pinned here.
"""
from __future__ import annotations

import json
import subprocess
import sys

import pytest
from celltype_column_eval import full, parse_curation, score_picks, subset, with_ground_truth
from celltype_column_eval.cli import FROZEN_PICKS, main

FROZEN_SCORES = FROZEN_PICKS.parent / "n73_scores.json"


def test_curation_snapshot_ships_with_the_package():
    curation = parse_curation()
    assert len(curation) > 100
    for dsid, entry in curation.items():
        assert entry["columns"], f"{dsid} retained with no curated column"
        assert entry["groups"]


def test_celltype_filter_drops_the_other_author_categories():
    """The sheets also record clonotypes, donor ids and demographics. Scoring
    against those would inflate the denominator with things no picker should
    ever pick."""
    filtered = parse_curation()
    unfiltered = parse_curation(filter_celltype=False)
    assert set(filtered) <= set(unfiltered)
    for dsid in filtered:
        assert set(filtered[dsid]["columns"]) <= set(unfiltered[dsid]["columns"])
    assert sum(len(v["columns"]) for v in filtered.values()) < \
        sum(len(v["columns"]) for v in unfiltered.values())


def test_manifest_is_the_whole_test_set():
    manifest = full()
    assert len(manifest) == 74
    for dsid, entry in manifest.items():
        assert entry["url"].endswith(f"{dsid}.h5ad"), dsid
        assert entry["url"].startswith("https://datasets.cellxgene.cziscience.com/")


def test_one_manifest_entry_is_known_unreadable():
    """Kept rather than dropped: removing it would quietly overstate coverage."""
    unreadable = [d for d, e in full().items() if not e["n_cells"]]
    assert len(unreadable) == 1


def test_subset_is_small_and_each_case_says_why():
    chosen = subset()
    assert 3 <= len(chosen) <= 10, "the default eval must stay cheap"
    assert set(chosen) <= set(full())
    for dsid, entry in chosen.items():
        assert len(entry["why"]) > 60, f"{dsid} has no stated reason for being here"


def test_subset_covers_the_traps_the_rules_exist_for():
    truth = with_ground_truth(subset())
    # a dataset where the right answer is to pick nothing
    assert any(not e["curated"] for e in truth.values())
    # a dataset with a multi-level hierarchy
    assert any(len(e["curated"]) >= 3 for e in truth.values())
    # a range of obs sizes, so cost behaviour is exercised too
    sizes = [e["n_cells"] for e in truth.values()]
    assert min(sizes) < 5_000 and max(sizes) > 100_000


def test_ground_truth_join_covers_every_dataset():
    truth = with_ground_truth()
    assert set(truth) == set(full())
    assert sum(1 for e in truth.values() if not e["curated"]) == 3


def test_frozen_baseline_rescores_to_its_stored_value():
    """The n=73 baseline must survive a round trip through the metrics and the
    curation snapshot as shipped. If either drifts, this is what notices."""
    frozen = json.loads(FROZEN_SCORES.read_text())
    picks = {d: v["picks"] for d, v in json.loads(FROZEN_PICKS.read_text()).items()}
    rescored = score_picks(picks, parse_curation())

    assert rescored["overall"]["n"] == 73
    assert rescored["overall"]["hit_rate"]["k"] == frozen["overall"]["hit_rate"]["k"]
    for metric in ("jaccard", "precision", "recall"):
        assert rescored["overall"][metric]["mean"] == \
            pytest.approx(frozen["overall"][metric]["mean"], abs=1e-9), metric


def test_the_stored_baseline_still_matches_what_was_published():
    """The shipped snapshot carries a CL_KG typo correction made after the
    original run, so the rescored figures move slightly. They must move by an
    amount too small to change the claim -- otherwise the published number needs
    withdrawing, not a wider tolerance."""
    frozen = json.loads(FROZEN_SCORES.read_text())
    published = frozen["_provenance"]["as_published"]
    for metric, value in published.items():
        assert frozen["overall"][metric]["mean"] == pytest.approx(value, abs=0.01), metric
    assert frozen["overall"]["hit_rate"]["k"] == \
        frozen["_provenance"]["as_published_hit_rate"]["k"]


# --- the CLI contract --------------------------------------------------------

def test_cli_datasets_defaults_to_the_subset(capsys):
    assert main(["datasets"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert set(payload) == set(subset())
    assert "curated" in next(iter(payload.values()))


def test_cli_datasets_all(capsys):
    assert main(["datasets", "--all"]) == 0
    assert len(json.loads(capsys.readouterr().out)) == 74


def test_cli_score_accepts_both_picks_shapes(tmp_path, capsys):
    bare = tmp_path / "bare.json"
    bare.write_text(json.dumps({"d": ["A"]}))
    rich = tmp_path / "rich.json"
    rich.write_text(json.dumps({"d": {"picks": ["A"], "reasoning": "because"}}))
    main(["score", str(bare)])
    first = json.loads(capsys.readouterr().out)
    main(["score", str(rich)])
    assert json.loads(capsys.readouterr().out) == first


def test_cli_score_baseline_is_like_for_like(capsys):
    """The baseline must be scored on the same datasets as the run, not on all
    73 -- otherwise a 6-dataset run is compared against a different test set."""
    picks = FROZEN_PICKS.parent / "n73_picks.json"
    main(["score", str(picks), "--baseline"])
    payload = json.loads(capsys.readouterr().out)
    assert payload["baseline"]["n_shared_datasets"] == payload["overall"]["n"]


def test_cli_version():
    out = subprocess.run([sys.executable, "-m", "celltype_column_eval.cli", "--version"],
                         capture_output=True, text=True)
    assert "celltype-column-eval" in out.stdout
