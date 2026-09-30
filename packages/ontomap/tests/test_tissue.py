"""Tissue, including the modifiers the other fields drive."""

from conftest import FakeUbergraph, make_index
from ontomap import tissue

INDEX = make_index(
    "UBERON",
    [
        ("UBERON:0002107", "liver", "label"),
        ("UBERON:0002370", "thymus", "label"),
        ("UBERON:0000990", "reproductive system", "label"),
        ("UBERON:0000964", "cornea", "label"),
        ("UBERON:0000966", "retina", "label"),
    ],
)

GRAPH = FakeUbergraph(
    descendants={"UBERON:0000990": {"UBERON:0000474", "UBERON:0000079"}},
    labels={"UBERON:0000474": "female reproductive system",
            "UBERON:0000079": "male reproductive system",
            "UBERON:0004161": "septum transversum"},
    common=[{"id": "UBERON:0010230", "label": "eyeball of camera-type eye",
             "information_content": 45.6, "definition": None}],
    develops_from={"UBERON:0002107": [
        {"id": "UBERON:0004161", "label": "septum transversum",
         "relation": "develops_from", "germ_layer_prone": False}]},
    xrefs={"UBERON:0002107": ["EHDAA2:0000997"], "UBERON:0004161": ["EHDAA2:0001829"]},
)


def test_a_sort_gate_is_not_anatomy():
    result = tissue.resolve("CD45+ sorted cells", INDEX, GRAPH)
    assert result.match.rule == "not_a_tissue"
    assert result.tissue_type == "cell culture"


def test_a_disease_qualifier_moves_to_sampled_site_condition():
    result = tissue.resolve("tumour liver", INDEX, GRAPH)
    assert result.match.term_id == "UBERON:0002107"
    assert result.sampled_site_condition == "diseased"


def test_sex_specialisation_needs_the_sex_field_and_proves_the_descent():
    context = tissue.Context(sex_term="PATO:0000383")
    result = tissue.resolve("reproductive system", INDEX, GRAPH, context)
    assert result.match.term_id == "UBERON:0000474"
    assert result.term_mature_id == "UBERON:0000990"


def test_a_pooled_library_is_never_specialised():
    context = tissue.Context(sex_term="PATO:0000383", sex_mixed=True)
    result = tissue.resolve("reproductive system", INDEX, GRAPH, context)
    assert result.match.term_id == "UBERON:0000990"


def test_the_precursor_is_substituted_only_when_the_age_rules_the_organ_out():
    early = tissue.resolve("liver", INDEX, GRAPH, tissue.Context(dpf_start=20, dpf_end=20))
    assert early.match.term_id == "UBERON:0004161"
    assert early.match.match_type == "exact_developmental"
    assert early.term_mature_id == "UBERON:0002107"

    later = tissue.resolve("liver", INDEX, GRAPH, tissue.Context(dpf_start=90, dpf_end=90))
    assert later.match.term_id == "UBERON:0002107"


def test_no_age_means_no_substitution():
    result = tissue.resolve("liver", INDEX, GRAPH)
    assert result.match.term_id == "UBERON:0002107"


def test_a_composite_rolls_up_to_what_contains_every_part():
    result = tissue.resolve("cornea and retina", INDEX, GRAPH)
    assert result.match.term_id == "UBERON:0010230"
    assert result.match.match_type == "broad_by_partonomy"
    # The roll-up is a real loss of resolution, so the parts survive verbatim.
    assert result.parts_free_text == "cornea; retina"


def test_a_composite_whose_parts_span_systems_is_refused():
    graph = FakeUbergraph(
        common=[{"id": "UBERON:0000949", "label": "endocrine system",
                 "information_content": 45.1, "definition": None}],
        ancestors={"UBERON:0000949": {"UBERON:0015203"}},
    )
    result = tissue.resolve("liver and thymus", INDEX, graph)
    assert result.match.term_id is None
    assert "spans_organ_systems" in result.match.flags


def test_an_unresolvable_part_blocks_the_roll_up():
    result = tissue.resolve("liver and mid vertebrae", INDEX, GRAPH)
    assert result.match.rule == "composite_unresolved"
    assert result.match.term_id is None


def test_a_placeholder_is_matched_whole_not_as_a_substring():
    """"sorted liver" is still a sort gate; "liver and unknown region" is not a placeholder."""
    assert tissue.resolve("unknown", INDEX, GRAPH).match.rule == "placeholder"
    assert tissue.resolve("sorted liver", INDEX, GRAPH).match.rule == "not_a_tissue"
    assert tissue.resolve("liver and unknown region", INDEX, GRAPH).match.rule != "placeholder"
