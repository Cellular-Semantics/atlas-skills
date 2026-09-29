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
    from celltype_column_eval.curation import _ADDITIONS

    filtered = parse_curation()
    unfiltered = parse_curation(filter_celltype=False)
    assert set(filtered) <= set(unfiltered)
    for dsid in filtered:
        # Reviewed additions are in the filtered view by construction and are
        # deliberately absent from the raw one.
        assert set(filtered[dsid]["columns"]) - set(_ADDITIONS.get(dsid, [])) \
            <= set(unfiltered[dsid]["columns"])
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


def test_the_baselines_divergence_from_the_published_figure_is_accounted_for():
    """The shipped gold set is no longer the one the 0.8079 was scored against:
    an upstream typo fix, four capitalisation fixes, and the columns accepted in
    the 2026-09-29 review. So the baseline moves, and that is intended.

    What must hold is that the divergence is *documented* -- both figures kept,
    reasons named -- rather than quietly absorbed. A numeric tolerance would
    only have to be widened each time the gold set is legitimately revised,
    until it stopped meaning anything.
    """
    prov = json.loads(FROZEN_SCORES.read_text())["_provenance"]
    assert set(prov["as_published"]) == {"jaccard", "precision", "recall"}
    assert set(prov["rescored_against_corrected_curation"]) == set(prov["as_published"])
    for reason in ("typo", "capitalisation", "review"):
        assert reason in prov["note"], f"the note does not say why it moved: {reason}"


def test_curation_fixes_did_not_change_which_datasets_were_hit():
    """A strong invariant across every gold-set revision so far: correcting or
    extending the curation changes how *well* the frozen picker did, never
    whether it found anything at all. If this breaks, a revision has removed a
    dataset's only correct answer and wants looking at."""
    frozen = json.loads(FROZEN_SCORES.read_text())
    assert frozen["overall"]["hit_rate"]["k"] == \
        frozen["_provenance"]["as_published_hit_rate"]["k"] == 72


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


def test_known_transcription_fixes_are_applied():
    """Four curated names capitalise a column that is lowercase in obs. Applied
    on read so the shipped CSVs stay a faithful copy of the CL_KG sheets."""
    from celltype_column_eval.curation import _CORRECTIONS

    columns = set(parse_curation()["ac818189-5c6b-48d2-8bf1-f7511de7b5a9"]["columns"])
    for wrong, right in _CORRECTIONS["ac818189-5c6b-48d2-8bf1-f7511de7b5a9"].items():
        assert right in columns
        assert wrong not in columns


def test_reviewed_additions_are_applied():
    """Columns accepted in the 2026-09-29 curation review. Applied on read so
    the shipped CSVs stay a faithful copy of the CL_KG sheets."""
    from celltype_column_eval.curation import _ADDITIONS

    curation = parse_curation()
    for dsid, extra in _ADDITIONS.items():
        assert set(extra) <= set(curation[dsid]["columns"]), dsid


def test_additions_do_not_leak_into_the_unfiltered_view():
    """The unfiltered view is 'what the sheets say', full stop. Adding to it
    would make the raw snapshot unrecoverable."""
    from celltype_column_eval.curation import _ADDITIONS

    unfiltered = parse_curation(filter_celltype=False)
    dsid = "443f7fb8-2a27-47c3-98f6-6a603c7a294e"
    assert _ADDITIONS[dsid][0] not in unfiltered.get(dsid, {}).get("columns", [])


def test_predicted_label_columns_are_still_out():
    """scanvi_label and transf_ann_level_* are model output, not author
    assertion. Section 3.2 of the review is open; until it is settled they must
    not drift into the gold set."""
    curation = parse_curation()
    for dsid in ("b13072bd-9cb6-42ca-9f4f-01252baef273",
                 "b351804c-293e-4aeb-9c4c-043db67f4540"):
        cols = curation[dsid]["columns"]
        assert "scanvi_label" not in cols
        assert not [c for c in cols if c.startswith("transf_ann_level_")]
