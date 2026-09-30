import json

import pytest

from ontomap import evaluate, extract, fold
from ontomap.config import Config
from ontomap.errors import OntomapError

CONFIG = Config.from_dict(
    {
        "fields": {
            "stage": [{"column": "age", "unit_column": "age_unit"}],
            "tissue": ["Organ"],
        },
        "scope_filter": {"column": "in_atlas", "include": ["true"]},
    }
)

ROWS = [
    {"Organ": "liver", "age": "13", "age_unit": "pcw", "in_atlas": "true"},
    {"Organ": "colon", "age": "14", "age_unit": "pcw", "in_atlas": "false"},
]


def test_out_of_scope_rows_are_flagged_not_dropped():
    """A correctly-mapped term for a sample the atlas never ingested is not an error.

    Dropping the row hides the discrepancy; keeping it flagged explains it.
    """
    records = extract.extract(ROWS, CONFIG)
    assert [r["scope"] for r in records] == ["in_scope", "out_of_scope"]


def test_the_unit_column_is_carried_alongside_the_value():
    records = extract.extract(ROWS, CONFIG)
    assert records[0]["raw"]["stage"][0] == {
        "column": "age", "role": "primary", "value": "13", "unit": "pcw", "frame": None
    }


def test_values_are_verbatim():
    records = extract.extract([{**ROWS[0], "Organ": "  Liver Tissue  "}], CONFIG)
    assert records[0]["raw"]["tissue"][0]["value"] == "Liver Tissue"


def test_a_missing_declared_column_is_an_error_not_a_silent_skip():
    with pytest.raises(OntomapError, match="not in the table"):
        extract.extract([{"Organ": "liver"}], CONFIG)


def test_distinct_values_are_counted_so_effort_follows_the_cells():
    rows = [{"Organ": "liver", "age": "1", "age_unit": "pcw", "in_atlas": "true"}] * 3
    rows += [{"Organ": "thymus", "age": "1", "age_unit": "pcw", "in_atlas": "true"}]
    counts = extract.distinct_values(extract.extract(rows, CONFIG), "tissue")
    assert list(counts) == ["liver", "thymus"]
    assert counts["liver"] == 3


def test_judgement_wins_but_stays_distinguishable_from_a_rule():
    records = [
        {"row": 0, "scope": "in_scope",
         "mapped": {"tissue": {"raw": "skin", "term_id": None, "rule": "candidates_only",
                               "needs_review": True}}}
    ]
    judgements = fold.load_judgements(
        [{"field": "tissue", "raw_value": "skin", "term_id": "UBERON:0002097",
          "term_name": "skin of body", "match_type": "exact", "basis": "definition text",
          "rationale": "the intended term", "curator": "agent"}]
    )
    folded = fold.fold(records, judgements)
    result = folded[0]["mapped"]["tissue"]
    assert result["term_id"] == "UBERON:0002097"
    assert result["curator"] == "agent"
    # What the rules said is preserved, so a silent override can be audited.
    assert result["rule_outcome"]["rule"] == "candidates_only"


def test_evaluation_reports_per_rule_and_names_untested_paths():
    """An aggregate hides everything. 15/15 was once true while `skin` was wrong.

    Every gold string hit an exact label, so the fuzzy path was never exercised
    and the aggregate was both accurate and useless.
    """
    records = [
        {"row": 0, "scope": "in_scope",
         "mapped": {"tissue": {"term_id": "UBERON:0002107", "rule": "exact_label"}}},
        {"row": 1, "scope": "in_scope",
         "mapped": {"tissue": {"term_id": "UBERON:0000014", "rule": "token_set",
                               "raw": "skin"}}},
    ]
    report = evaluate.compare(records, {0: {"tissue": "UBERON:0002107"}}, field="tissue")
    assert report["per_rule"]["exact_label"]["accuracy"] == 1.0
    assert "token_set" in report["unevaluated_paths"]
    assert report["per_rule"]["token_set"]["evaluated"] is False


def test_refusals_are_counted_separately_from_errors():
    records = [
        {"row": 0, "scope": "in_scope",
         "mapped": {"tissue": {"term_id": None, "rule": "candidates_only"}}}
    ]
    report = evaluate.compare(records, {0: {"tissue": "UBERON:0002097"}}, field="tissue")
    assert report["unscored"]["refused"] == 1
    assert report["scored"] == 0


def test_config_rejects_an_unknown_target_field():
    with pytest.raises(OntomapError, match="unknown target field"):
        Config.from_dict({"fields": {"celltype": ["x"]}})


def test_config_round_trips_through_json(tmp_path):
    path = tmp_path / "c.json"
    path.write_text(json.dumps({"fields": {"tissue": ["Organ"]}}), encoding="utf-8")
    assert Config.load(path).columns() == ["Organ"]
