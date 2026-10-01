from conftest import FakeUbergraph
from ontomap.ladder import Match
from ontomap.reconcile import reconcile


def m(raw, term_id, name, rule="exact_label"):
    return Match(raw=raw, term_id=term_id, term_name=name, rule=rule, match_type="exact")


def test_a_refinement_inside_the_primary_is_taken_and_the_edge_proves_it():
    graph = FakeUbergraph(ancestors={"UBERON:0008952": {"UBERON:0002048"}})
    out = reconcile(
        {"Organ": m("lung", "UBERON:0002048", "lung"),
         "Organ_part": m("upper lobe of left lung", "UBERON:0008952", "upper lobe of left lung")},
        graph,
    )
    assert out.agreement == "refined"
    assert out.match.term_id == "UBERON:0008952"
    assert out.match.rule == "refined_by_Organ_part"


def test_columns_that_do_not_subsume_each_other_are_a_conflict_not_a_tie():
    graph = FakeUbergraph(ancestors={"UBERON:0002048": set(), "UBERON:0000948": set()})
    out = reconcile(
        {"Organ": m("lung", "UBERON:0002048", "lung"),
         "Organ_part": m("heart", "UBERON:0000948", "heart")},
        graph,
    )
    assert out.agreement == "conflict"
    assert out.match.term_id is None
    assert "column_conflict" in out.match.flags


def test_agreement_between_columns_is_recorded():
    graph = FakeUbergraph()
    out = reconcile(
        {"a": m("liver", "UBERON:0002107", "liver"),
         "b": m("liver", "UBERON:0002107", "liver")},
        graph,
    )
    assert out.agreement == "agree"


def test_an_empty_column_does_not_supply_the_outcome():
    """Reporting 'null' from an empty primary hides the informative failure.

    One column was blank and the other parsed to a day window with no covering
    term. The blank column is not the answer.
    """
    graph = FakeUbergraph()
    out = reconcile(
        {"Developmental_stage": Match(raw="", rule="null"),
         "age": Match(raw="90 pcw", rule="no_covering_term", needs_review=True)},
        graph,
    )
    assert out.match.rule == "no_covering_term"
    assert out.winner == "age"
