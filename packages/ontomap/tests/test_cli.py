"""The CLI contract: JSON on stdout, and exit 2 when a check does not check out."""

import json

import pytest

from ontomap.cli import main

CONFIG = {"fields": {"tissue": ["Organ"]}, "scope_filter": {"column": "keep", "include": ["y"]}}
TABLE = "Organ,keep\nliver,y\ncolon,n\n"


@pytest.fixture
def workspace(tmp_path):
    (tmp_path / "config.json").write_text(json.dumps(CONFIG), encoding="utf-8")
    (tmp_path / "samples.csv").write_text(TABLE, encoding="utf-8")
    return tmp_path


def test_extract_writes_records_and_prints_a_summary(workspace, capsys):
    code = main(
        ["extract", str(workspace / "samples.csv"),
         "--config", str(workspace / "config.json"),
         "--out", str(workspace / "extracted.json")]
    )
    assert code == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary == {"rows": 2, "in_scope": 1, "out_of_scope": 1,
                       "distinct_values": {"tissue": 2}}


def test_validate_exits_2_when_a_gate_fails(workspace, capsys, monkeypatch):
    records = {"records": [{"row": 0, "scope": "in_scope", "mapped": {
        "tissue": {"term_id": "UBERON:0002107", "term_name": "pancreas"}}}]}
    (workspace / "folded.json").write_text(json.dumps(records), encoding="utf-8")

    from ontomap import ols as ols_module

    monkeypatch.setattr(
        ols_module.Ols, "lookup",
        lambda self, term_id: {"id": term_id, "label": "liver", "obsolete": False},
    )
    code = main(["validate", str(workspace / "folded.json")])
    assert code == 2
    report = json.loads(capsys.readouterr().out)
    assert report["failed"] == 1
    assert report["failures"][0]["gate"] == "LABEL_MATCHES"


def test_validate_exits_0_when_everything_passes(workspace, capsys, monkeypatch):
    records = {"records": [{"row": 0, "scope": "in_scope", "mapped": {
        "tissue": {"term_id": "UBERON:0002107", "term_name": "liver"}}}]}
    (workspace / "folded.json").write_text(json.dumps(records), encoding="utf-8")

    from ontomap import ols as ols_module

    monkeypatch.setattr(
        ols_module.Ols, "lookup",
        lambda self, term_id: {"id": term_id, "label": "liver", "obsolete": False},
    )
    assert main(["validate", str(workspace / "folded.json")]) == 0


def test_version_is_available(capsys):
    with pytest.raises(SystemExit) as exit_info:
        main(["--version"])
    assert exit_info.value.code == 0
    assert "ontomap" in capsys.readouterr().out
