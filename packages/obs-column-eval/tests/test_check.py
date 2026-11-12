"""check-picks: a report is held to its schema and to the obs it names.

What matters most is the failure a summary would hide -- a column the picker
named that is not in obs. Each test writes a real obs table in the format the
skill produces, so the existence check reads what it will read in use.
"""
from __future__ import annotations

import json

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from obs_column_eval.check import check_report, consistency_problems, source_columns
from obs_column_eval.cli import main

OBS_COLUMNS = ["author_cell_type", "celltype.l2", "Organ", "Disease", "cell_type",
               "disease", "seurat_clusters"]


@pytest.fixture
def workdir(tmp_path):
    table = pa.table({c: ["a", "b"] for c in OBS_COLUMNS})
    pq.write_table(table, tmp_path / "obs.parquet")
    return tmp_path


def write(workdir, **overrides):
    report = {
        "schema_version": 1,
        "source": "obs.parquet",
        "requested": ["cell_type", "tissue", "disease"],
        "picks": {"cell_type": ["author_cell_type", "celltype.l2"],
                  "tissue": ["Organ"], "disease": ["Disease"]},
        "reasoning": {"author-celltype-picker": "labels",
                      "author-sample-field-picker": "organ and diagnosis"},
    }
    report.update(overrides)
    path = workdir / "picks.json"
    path.write_text(json.dumps(report))
    return path


def test_a_faithful_report_passes(workdir):
    result = check_report(write(workdir))
    assert result == {**result, "ok": True, "problems": []}


def test_an_invented_column_is_caught(workdir):
    result = check_report(write(workdir, picks={
        "cell_type": ["author_cell_type", "celltype.l3"], "tissue": [], "disease": []}))
    assert not result["ok"]
    assert any("`celltype.l3` is not a column" in p for p in result["problems"])


def test_a_recased_column_is_caught_and_the_real_name_offered(workdir):
    result = check_report(write(workdir, picks={
        "cell_type": ["Author_Cell_Type"], "tissue": [], "disease": []}))
    assert result["problems"] == [
        "picks/cell_type: `Author_Cell_Type` is not a column of the source obs; "
        "did you mean `author_cell_type`?"]


def test_a_portal_field_is_caught_even_though_it_exists(workdir):
    """`disease` is in obs -- it is CELLxGENE's. Existing is not enough."""
    result = check_report(write(workdir, picks={
        "cell_type": [], "tissue": [], "disease": ["disease"]}))
    assert not result["ok"]


def test_a_schema_failure_does_not_hide_a_missing_column(workdir):
    """Found in a live test: a portal-field pick stopped the check, and the
    misspelt column beside it went unreported until the first was fixed."""
    result = check_report(write(workdir, picks={
        "cell_type": ["author_cell_type", "cell_type"],
        "tissue": ["layer_dissection"], "disease": []}))
    assert len(result["problems"]) == 2
    assert any("`cell_type` is the portal's standardised field" in p
               for p in result["problems"])
    assert any("`layer_dissection` is not a column" in p for p in result["problems"])


def test_a_misnamed_field_type_still_has_its_columns_checked(workdir):
    result = check_report(write(workdir, picks={"celltype": ["nope"]}))
    assert any("`nope` is not a column" in p for p in result["problems"])


def test_unchecked_columns_are_said_to_be_unchecked(workdir):
    result = check_report(write(workdir, source=""))
    assert "columns not checked against obs: no usable `source`" in result["problems"]


def test_the_portal_field_message_does_not_quote_a_regex(workdir):
    result = check_report(write(workdir, picks={
        "cell_type": ["cell_type_ontology_term_id"], "tissue": [], "disease": []}))
    (problem,) = [p for p in result["problems"] if "never a pick" in p]
    assert "pattern" not in problem
    assert "is an ontology term id column, never a pick" in problem


def test_a_missing_source_fails_rather_than_passing_unchecked(workdir):
    result = check_report(write(workdir, source="elsewhere/obs.parquet"))
    assert not result["ok"]
    assert "does not exist" in result["problems"][0]


def test_not_json_is_a_problem_not_a_crash(workdir):
    path = workdir / "picks.json"
    path.write_text("{not json")
    assert check_report(path)["problems"][0].startswith("not valid JSON")


def test_a_requested_field_type_must_have_a_key():
    problems = consistency_problems({
        "requested": ["cell_type", "tissue"], "picks": {"cell_type": []},
        "reasoning": {"author-celltype-picker": "x", "author-sample-field-picker": "y"}})
    assert problems == ["picks: `tissue` was requested and has no key; write "
                        "`\"tissue\": []` if the picker found nothing"]


def test_an_unrequested_field_type_is_flagged():
    problems = consistency_problems({
        "requested": ["cell_type"], "picks": {"cell_type": [], "tissue": []},
        "reasoning": {"author-celltype-picker": "x"}})
    assert problems == ["picks: `tissue` was not requested; add it to `requested` "
                        "or drop it"]


def test_each_dispatched_picker_must_leave_its_reasoning():
    problems = consistency_problems({
        "requested": ["cell_type", "disease"], "picks": {"cell_type": [], "disease": []},
        "reasoning": {"author-celltype-picker": "x"}})
    assert problems == ["reasoning: no entry from `author-sample-field-picker`, "
                        "which picks disease"]


@pytest.mark.parametrize("fmt", ["csv", "tsv"])
def test_columns_are_read_from_a_delimited_obs(tmp_path, fmt):
    sep = "\t" if fmt == "tsv" else ","
    path = tmp_path / f"obs.{fmt}"
    # pandas' layout: the unnamed index first, under an empty header.
    path.write_text(f"{sep}Organ{sep}age\nc1{sep}x{sep}1\n")
    assert source_columns(path) == ["Organ", "age"]


def test_columns_are_read_from_a_text_profile(tmp_path):
    path = tmp_path / "profile.txt"
    path.write_text("obs profile: obs.parquet\n2 rows x 2 columns; 2 rows scanned.\n\n"
                    "name | kind | n_unique | measurement | sample values\n"
                    "Organ | categorical[1 cats] | 1 (constant) |  | 'x'\n"
                    "age | int64 | 2 | bounded 1..2 | 1, 2\n")
    assert source_columns(path) == ["Organ", "age"]


def test_an_unreadable_source_type_is_a_problem(workdir):
    (workdir / "obs.h5ad").write_bytes(b"")
    result = check_report(write(workdir, source="obs.h5ad"))
    assert "cannot read columns" in result["problems"][0]


def test_cli_exits_1_and_explains_on_stderr(workdir, capsys):
    path = write(workdir, picks={"cell_type": ["nope"], "tissue": [], "disease": []})
    assert main(["check-picks", str(path)]) == 1
    captured = capsys.readouterr()
    assert json.loads(captured.out)["ok"] is False
    assert "`nope` is not a column" in captured.err


def test_cli_exits_0_on_a_good_report(workdir, capsys):
    assert main(["check-picks", str(write(workdir))]) == 0
    assert capsys.readouterr().err == ""
