"""The picks.json contract: what the skill writes, and what its pickers return.

The schema is only worth having if the things that already exist conform to it.
So the frozen n=73 picks -- 73 real cell-type picker answers -- are held to the
picker-result shape, and the hand-curated sample-field entry is held to the
report shape. A schema that rejected either would be describing an imagined
skill, not this one.
"""
from __future__ import annotations

import json

import pytest
from jsonschema import Draft202012Validator
from obs_column_eval.cli import FROZEN_PICKS, PICKS_SCHEMA, main
from obs_column_eval.gold import FIELD_TYPES, sample_field_gold

SCHEMA = json.loads(PICKS_SCHEMA.read_text())


def errors(instance, definition: str | None = None) -> list[str]:
    """Validation errors against the report, or against one of its `$defs`."""
    schema = SCHEMA if definition is None else {
        "$defs": SCHEMA["$defs"], "$ref": f"#/$defs/{definition}"}
    return [e.message for e in Draft202012Validator(schema).iter_errors(instance)]


def report(**overrides) -> dict:
    base = {
        "schema_version": 1,
        "source": "obs.parquet",
        "requested": ["cell_type", "tissue"],
        "picks": {"cell_type": ["author_cell_type"], "tissue": []},
        "reasoning": {"author-celltype-picker": "author labels",
                      "author-sample-field-picker": "single-tissue atlas"},
    }
    base.update(overrides)
    return base


def test_the_schema_is_itself_valid():
    Draft202012Validator.check_schema(SCHEMA)


def test_the_schema_ships_inside_the_package():
    """It is read from the installed package by the CLI, so it has to be there
    and not only in the repo."""
    assert PICKS_SCHEMA.is_file()
    assert "obs_column_eval" in PICKS_SCHEMA.parts


def test_field_types_agree_with_the_package():
    """Two lists of the same five things drift unless something pins them."""
    assert tuple(SCHEMA["$defs"]["FieldType"]["enum"]) == FIELD_TYPES


def test_a_well_formed_report_passes():
    assert errors(report()) == []


#: The one frozen answer the schema rejects, and rightly. The picker took
#: `BICCN_ontology_term_id` -- an `*_ontology_term_id` column, which the skill
#: says is never a pick, and which no curation sheet lists. A real picker
#: error in the baseline, kept as found: the frozen picks are a record.
KNOWN_BAD_FROZEN = {"e48806af-87d1-45ae-843a-c7ee06eac672": "BICCN_ontology_term_id"}


def test_every_frozen_cell_type_answer_is_a_valid_picker_result():
    frozen = json.loads(FROZEN_PICKS.read_text())
    assert len(frozen) == 73
    bad = {dsid for dsid, answer in frozen.items()
           if errors(answer, "CellTypePickerResult")}
    assert bad == set(KNOWN_BAD_FROZEN)


def test_the_known_bad_frozen_answer_fails_only_on_the_portal_style_column():
    frozen = json.loads(FROZEN_PICKS.read_text())
    for dsid, column in KNOWN_BAD_FROZEN.items():
        answer = frozen[dsid]
        assert column in answer["picks"]
        fixed = {**answer, "picks": [c for c in answer["picks"] if c != column]}
        assert errors(fixed, "CellTypePickerResult") == []


def test_the_hand_curated_entry_fits_the_report_shape():
    for dsid, entry in sample_field_gold().items():
        cols = entry["columns"]
        as_report = report(dataset=dsid, requested=list(cols), picks=cols)
        assert errors(as_report) == [], dsid


def test_the_documented_picker_answers_are_valid():
    """The examples in the agent definitions, verbatim."""
    assert errors({"picks": ["col1", "col2"], "reasoning": "one sentence"},
                  "CellTypePickerResult") == []
    assert errors({"tissue": ["Organ", "Organ_part"],
                   "development_stage": ["Postnatal_age_years"],
                   "other_stage": [], "disease": ["Disease"],
                   "reasoning": "one or two sentences"},
                  "SampleFieldPickerResult") == []


@pytest.mark.parametrize("column", [
    "cell_type", "tissue", "development_stage", "disease",
    "cell_type_ontology_term_id", "BICCN_ontology_term_id",
])
def test_portal_fields_are_never_picks(column):
    assert errors(report(picks={"cell_type": [column], "tissue": []}))


@pytest.mark.parametrize("column", ["Disease", "Tissue", "cell_type_author", "celltype.l1"])
def test_author_columns_that_resemble_portal_fields_pass(column):
    """CELLxGENE's column is `disease`; the authors' is often `Disease`."""
    assert errors(report(picks={"cell_type": [column], "tissue": []})) == []


@pytest.mark.parametrize("broken", [
    {"picks": {"cell_types": ["x"]}},                    # misspelt field type
    {"picks": {"cell_type": "author_cell_type"}},        # a string, not a list
    {"picks": {"cell_type": ["x", "x"]}},                # a column twice
    {"picks": {"cell_type": [""]}},                      # an empty name
    {"picks": {}},                                       # nothing at all
    {"requested": []},
    {"requested": ["celltype"]},
    {"reasoning": {}},
    {"reasoning": {"picker": "why"}},                    # not a known agent
    {"schema_version": 2},
    {"source": ""},
    {"extra": True},
])
def test_malformed_reports_are_rejected(broken):
    assert errors(report(**broken))


@pytest.mark.parametrize("missing", ["schema_version", "source", "requested",
                                     "picks", "reasoning"])
def test_every_required_key_is_required(missing):
    r = report()
    del r[missing]
    assert errors(r)


def test_an_empty_pick_is_a_real_answer():
    assert errors(report(picks={"cell_type": [], "tissue": []})) == []


def test_cli_prints_the_schema(capsys):
    assert main(["schema"]) == 0
    assert json.loads(capsys.readouterr().out) == SCHEMA
