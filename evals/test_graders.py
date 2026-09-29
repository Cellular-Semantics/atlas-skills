"""Unit tests for the grading logic. No network, no spend."""
import pytest

from graders import Run, grade, grade_one, score

CAP_CALL = {"name": "Bash", "input": {
    "command": 'uvx --from git+... cap degs https://celltype.info/project/1030/dataset/3400 '
               '--labelset hgca_celltype_v1 --only "Tuft Progenitors" --vs "Tuft Cells"'}}


def run(answer="", calls=()):
    return Run(answer=answer, tool_calls=list(calls))


def test_command_matches_sees_bash_commands():
    r = run(calls=[CAP_CALL])
    assert grade_one({"kind": "command_matches", "pattern": r"cap\s+degs"}, r).passed
    assert grade_one({"kind": "command_matches", "pattern": "--vs"}, r).passed
    assert not grade_one({"kind": "command_matches", "pattern": "--group-by"}, r).passed


def test_command_matches_sees_structured_tool_input():
    # A check should pin behaviour, not the shape of the call that produced it.
    r = run(calls=[{"name": "Skill", "input": {"skill": "cap-degs", "args": "--vs X"}}])
    assert grade_one({"kind": "command_matches", "pattern": "cap-degs"}, r).passed


def test_command_not_matches():
    r = run(calls=[CAP_CALL])
    assert grade_one({"kind": "command_not_matches", "pattern": "h5ad-obs"}, r).passed
    assert not grade_one({"kind": "command_not_matches", "pattern": "cap degs"}, r).passed


def test_answer_matches_is_case_insensitive():
    r = run(answer="These are Cell-Cycle genes.")
    assert grade_one({"kind": "answer_matches", "pattern": "cell.cycle"}, r).passed


def test_answer_not_matches():
    r = run(answer="STMN1 does not discriminate the two.")
    assert grade_one({"kind": "answer_not_matches", "pattern": "indistinguishable"}, r).passed


def test_answer_any_of_counts_hits():
    r = run(answer="Top genes: TRPM5, GNAT3 and some others.")
    check = {"kind": "answer_any_of", "patterns": ["TRPM5", "GNAT3", "POU2F3"], "min_hits": 2}
    res = grade_one(check, r)
    assert res.passed and "TRPM5, GNAT3" in res.detail


def test_answer_any_of_below_threshold_fails():
    r = run(answer="Only TRPM5 here.")
    check = {"kind": "answer_any_of", "patterns": ["TRPM5", "GNAT3"], "min_hits": 2}
    assert not grade_one(check, r).passed


def test_answer_any_of_is_word_bounded():
    """Gene symbols are prefixes of one another: TPM1 must not match TPM10."""
    r = run(answer="TPM10 and PLCG21 were returned.")
    check = {"kind": "answer_any_of", "patterns": ["TPM1", "PLCG2"], "min_hits": 1}
    assert not grade_one(check, r).passed


def test_numeric_in_range():
    r = run(answer="Tuft Progenitors: 54.5% detected.")
    check = {"kind": "numeric_in_range", "pattern": r"Tuft Progenitors[^\d]{0,40}([\d.]+)\s*%",
             "min": 50, "max": 59}
    assert grade_one(check, r).passed
    assert not grade_one({**check, "min": 60, "max": 70}, r).passed


def test_numeric_in_range_reads_a_markdown_table_row():
    """Answers arrive as tables, so n_cells sits between the label and the percentage.
    A pattern that forbids intervening digits silently fails on the real output."""
    answer = ("| Cell type | n cells | % detected |\n"
              "| Tuft Progenitors | 686 | **54.5%** |\n"
              "| Tuft Cells | 2,993 | **47.1%** |\n")
    for label, want in (("Tuft Progenitors", 54.5), ("Tuft Cells", 47.1)):
        check = {"kind": "numeric_in_range",
                 "pattern": rf"{label}[^\n]{{0,120}}?([\d.]+)\s*%",
                 "min": want - 0.5, "max": want + 0.5}
        res = grade_one(check, run(answer=answer))
        assert res.passed, f"{label}: {res.detail}"


def test_numeric_in_range_with_no_capture_fails_clearly():
    res = grade_one({"kind": "numeric_in_range", "pattern": r"nope ([\d.]+)",
                     "min": 0, "max": 1}, run(answer="nothing here"))
    assert not res.passed and "no number captured" in res.detail


def test_numeric_in_range_rejects_a_non_number_capture():
    res = grade_one({"kind": "numeric_in_range", "pattern": r"value (\S+)",
                     "min": 0, "max": 1}, run(answer="value unknown"))
    assert not res.passed and "not a number" in res.detail


def test_unknown_kind_is_an_authoring_error():
    with pytest.raises(ValueError, match="unknown check kind"):
        grade_one({"kind": "vibes"}, run())


def test_a_failed_run_fails_every_check_rather_than_scoring_nothing():
    r = Run(error="timed out")
    checks = [{"kind": "answer_matches", "pattern": "x"},
              {"kind": "command_matches", "pattern": "y"}]
    results = grade(r, checks)
    assert len(results) == 2 and not any(x.passed for x in results)
    assert score(results) == 0.0
    assert "timed out" in results[0].detail


def test_score_is_the_pass_fraction():
    r = run(answer="TRPM5")
    checks = [{"kind": "answer_matches", "pattern": "TRPM5"},
              {"kind": "answer_matches", "pattern": "absent"}]
    assert score(grade(r, checks)) == 0.5


def test_why_is_surfaced_for_reporting():
    check = {"kind": "answer_matches", "pattern": "x", "why": "pins the conclusion"}
    assert grade_one(check, run(answer="x")).why == "pins the conclusion"


def test_a_spend_limit_is_classified_as_infrastructure():
    """A harness stop must be distinguishable from a skill regression, or a real
    failure gets buried under noise."""
    from graders import classify_error

    assert classify_error("You've hit your monthly spend limit · raise it at ...") \
        == "spend limit"
    assert classify_error("API Error: 429 rate limit exceeded") == "rate limit"
    assert classify_error("STMN1 is detected in 47% of Tuft Cells") is None


def test_numeric_present_scans_past_a_decoy():
    """An early grader anchored on the label and matched a percentage belonging to a
    different cell type in the same sentence."""
    answer = ("STMN1: Tuft Progenitors 54.5% vs Tuft Cells 47.1%. It ranks 15th of 94 "
              "labels for Tuft Progenitors, well behind Cycling Macrophages (94.9%).")
    assert grade_one({"kind": "numeric_present", "min": 53, "max": 56},
                     run(answer=answer)).passed
    assert grade_one({"kind": "numeric_present", "min": 45.5, "max": 48.5},
                     run(answer=answer)).passed


def test_numeric_present_survives_either_table_orientation():
    by_cell_type = "| Tuft Progenitors | 686 | 54.5% |\n| Tuft Cells | 2993 | 47.1% |"
    by_gene = "| gene | Tuft Progenitors | Tuft Cells |\n| STMN1 | 54.5% | 47.1% |"
    for answer in (by_cell_type, by_gene):
        assert grade_one({"kind": "numeric_present", "min": 53, "max": 56},
                         run(answer=answer)).passed


def test_numeric_present_reports_what_it_saw_when_it_fails():
    res = grade_one({"kind": "numeric_present", "min": 90, "max": 95},
                    run(answer="54.5% and 47.1%"))
    assert not res.passed and "54.5" in res.detail
