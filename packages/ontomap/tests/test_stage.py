"""Stage parsing, against the real vendored HsapDv table. No network."""

import pytest

from ontomap import stage


def test_carnegie_needs_no_conversion():
    for text in ("Carnegie stage 13", "CS13", "cs 13", "carnegie stage 013"):
        match = stage.parse(text)
        assert match.rule == "carnegie"
        assert match.term_name == "Carnegie stage 13"


def test_week_post_fertilization_resolves_by_day_window():
    match = stage.parse("13 pcw")
    assert match.term_name == "13th week post-fertilization stage"
    assert (match.dpf_start, match.dpf_end) == (84.0, 91.0)


def test_gestational_weeks_are_shifted_and_flagged():
    match = stage.parse("GW 15")
    assert match.term_name == "13th week post-fertilization stage"
    assert "gestational_shift_applied" in match.flags


def test_a_bare_number_has_no_scale_and_is_refused():
    # Sixty distinct values were once stranded because the unit lived in a
    # sibling column. Guessing a unit is worse than saying so.
    match = stage.parse("13")
    assert match.rule == "no_unit"
    assert match.term_id is None


def test_a_frame_is_not_a_unit():
    match = stage.parse("13", frame=stage.POST_FERTILIZATION)
    assert match.rule == "no_unit"


def test_unit_column_is_folded_in():
    match = stage.parse("13", unit="weeks")
    assert match.term_name == "13th week post-fertilization stage"


def test_several_stages_means_pooled_not_a_tie():
    match = stage.parse("8, 10, 12 pcw")
    assert match.rule == "multi_value"
    assert match.term_id is None
    assert "pooled" in match.flags


def test_postnatal_ages_are_named_as_such():
    assert stage.parse("3 months").rule == "postnatal"
    assert stage.parse("45 years").rule == "postnatal"


def test_carnegie_windows_are_closed_from_the_next_stage():
    # HsapDv gives Carnegie stage 12 a start_dpf and no end. Without closing it
    # no containment test can use it, and there are 23 such terms.
    table = stage.stage_table()
    assert table["HsapDv:0000019"]["end_dpf"] is not None
    assert table["HsapDv:0000019"].get("end_dpf_derived") is True


def test_early_embryo_days_reach_a_carnegie_term():
    # Carnegie terms are not in HsapDv's granular_stage subset -- all 23 are
    # flagged false -- so a subset-only filter threw away the only term that
    # could place day 20.
    match = stage.parse("20 dpf")
    assert match.term_name == "Carnegie stage 09"


def test_null_values_are_recorded_as_null_not_guessed():
    for text in ("", "NA", "unknown", "not reported"):
        assert stage.parse(text).rule == "null"


@pytest.mark.parametrize("day,expected", [(84.0, 2), (91.0, 2)])
def test_abutting_windows_report_both_terms(day, expected):
    # Windows abut rather than nest, so a boundary day genuinely matches two.
    covering = stage.terms_covering(day, day)
    weeks = [t for t in covering if "week post-fertilization" in (t["label"] or "")]
    assert len(weeks) == expected


def test_an_lmp_term_is_never_assigned_to_a_post_fertilization_value():
    """Everything is converted to days post-fertilization; LMP terms are not.

    "fourth LMP month stage" spans 77-105 dpf and so contains a 13-14 pcw
    range arithmetically, but it counts from the last menstrual period. Taking
    it would be the two-week frame error arriving by a new route.
    """
    match = stage.parse("13-14 pcw")
    assert match.term_id is None
    assert match.rule == "no_granular_term"
    # Still offered, because a gestational study may legitimately want one.
    assert any("LMP" in (c["label"] or "") for c in match.candidates)


def test_the_narrowest_covering_term_wins_for_a_single_week():
    match = stage.parse("16 pcw")
    assert match.term_name == "16th week post-fertilization stage"
