"""The run log: the committed run files and the index generated from them."""
from __future__ import annotations

import json

import pytest
from run_log import (
    REQUIRED_RUN_KEYS,
    RUNS,
    SCHEMA,
    build_record,
    render_index,
    run_filename,
    write_run,
)


def _run(**over) -> dict:
    run = {k: None for k in REQUIRED_RUN_KEYS}
    run.update(date="2026-11-18", scope="l4", note="", cost_usd=1.0,
               picker={"commit": "abc1234"}, unreadable=[], no_picks_returned=[])
    run.update(over)
    return run


def _cell_type() -> dict:
    block = {"n": 1, "jaccard": {"mean": 1.0}, "hit_rate": {"k": 1, "n": 1}}
    row = {"dsid": "d1", "jaccard": 1.0, "picks": ["a"], "missed_by_agent": [],
           "agent_extras": []}
    return {"by_tier": {"tiers": {"l4": block}, "all": block, "by_group": {}},
            "per_dataset": [row]}


def test_a_run_needs_its_metadata():
    with pytest.raises(ValueError, match="lacks"):
        build_record(run={"date": "x"}, cell_type=_cell_type(), baselines={}, manifest={})


def test_a_record_tags_datasets_with_their_tier_and_carries_the_baseline_delta():
    base = {"l4": {"source": "frozen l4", "overall": {"n": 1, "jaccard": {"mean": 0.5}}}}
    record = build_record(run=_run(), cell_type=_cell_type(), baselines=base,
                          manifest={"d1": {"tier": "l4"}})
    assert record["per_dataset"][0]["tier"] == "l4"
    assert record["tiers"]["l4"]["baseline"]["delta_jaccard"] == pytest.approx(0.5)
    assert record["all"] is None  # one tier: no combined figure


def test_a_run_file_is_never_overwritten(tmp_path):
    record = build_record(run=_run(), cell_type=_cell_type(), baselines={}, manifest={})
    first, second = write_run(record, tmp_path), write_run(record, tmp_path)
    assert first != second and second.name.endswith("-2.json")
    assert run_filename(record["run"], tmp_path).name.endswith("-3.json")
    index = (tmp_path / "README.md").read_text()
    assert first.name in index and second.name in index


def test_committed_run_files_are_complete():
    files = sorted(RUNS.glob("*.json"))
    assert files, "the run log is empty"
    for path in files:
        record = json.loads(path.read_text())
        assert record["schema"] == SCHEMA, path.name
        assert set(record["run"]) >= REQUIRED_RUN_KEYS, path.name
        assert path.name.startswith(f"{record['run']['date']}-{record['run']['scope']}-")
        assert record["per_dataset"], path.name


def test_the_index_is_up_to_date():
    """A run file added or edited by hand must come with a regenerated index:
    `python3 evals/author-annotation-columns/run_log.py`."""
    assert (RUNS / "README.md").read_text() == render_index(RUNS)
