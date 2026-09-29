"""The cases' own checks, exercised against realistic answers.

Free and offline. A grader regex that fails a correct answer is worse than no
check at all -- it makes a green suite mean nothing -- so every negative check
here is shown to pass the answer it should pass and fail the one it should fail.
"""
from __future__ import annotations

import json
import pathlib
import re

import pytest

from graders import KINDS, Run, grade

CASES = pathlib.Path(__file__).parent / "cases"


def load(name: str) -> list[dict]:
    return json.loads((CASES / name / "checks.json").read_text())["checks"]


def answer_checks(name: str) -> list[dict]:
    return [c for c in load(name) if c["kind"].startswith("answer")]


def verdict(checks: list[dict], answer: str = "", commands: str = "") -> bool:
    calls = [{"name": "Bash", "input": {"command": commands}}] if commands else []
    return all(r.passed for r in grade(Run(answer=answer, tool_calls=calls), checks))


# --- every case is well formed ----------------------------------------------

@pytest.mark.parametrize("case_dir", sorted(p.name for p in CASES.iterdir() if p.is_dir()))
def test_case_is_complete(case_dir):
    spec = json.loads((CASES / case_dir / "checks.json").read_text())
    assert (CASES / case_dir / "prompt.md").read_text().strip()
    assert (CASES / case_dir / "graders" / "criteria.md").read_text().strip()
    assert spec["tags"]
    for check in spec["checks"]:
        assert check["kind"] in KINDS
        assert len(check.get("why", "")) > 20, "a check with no stated purpose is noise"
        if "pattern" in check:
            re.compile(check["pattern"])


# --- the rejection checks must not punish a better answer --------------------

def test_rejecting_a_cluster_column_out_loud_is_not_penalised():
    """`leiden` appearing in the answer is not the failure -- picking it is. An
    answer that explains why it was rejected is the best possible answer and
    must score full marks."""
    checks = answer_checks("numeric-clusters-rejected")
    assert verdict(checks, "The author cell-type column is `free_annotation` (14 labels). "
                           "I rejected `leiden` and `louvain`: their values are integers "
                           "stored as strings, so they are cluster indices, not labels.")


def test_picking_a_cluster_column_fails():
    checks = answer_checks("numeric-clusters-rejected")
    assert not verdict(checks, "The author cell-type columns are free_annotation, "
                               "leiden and louvain.")
    assert not verdict(checks, "I picked leiden as the author annotation.")


def test_missing_the_real_label_fails_even_with_the_clusters_rejected():
    checks = answer_checks("numeric-clusters-rejected")
    assert not verdict(checks, "No author cell-type column; leiden and louvain are "
                               "cluster indices.")


def test_seurat_clusters_named_as_rejected_is_not_penalised():
    checks = answer_checks("label-beside-cluster-index")
    assert verdict(checks, "`author_cell_type` holds the annotation: T cell 8,211; "
                           "Macrophage 4,002; Fibroblast 1,530. `seurat_clusters` is a "
                           "20-level integer cluster id and is not a label column.")


def test_seurat_clusters_presented_as_the_answer_fails():
    checks = answer_checks("label-beside-cluster-index")
    assert not verdict(checks, "The author cell-type columns are author_cell_type and "
                               "seurat_clusters. Counts: T cell 8,211.")


def test_constant_case_accepts_any_wording_of_the_finding():
    checks = answer_checks("constant-columns")
    for phrasing in (
        "Cell.class, Cell.group and Lineage are all constant across the 7,274 cells, so "
        "there is no per-cell author cell-type annotation here.",
        "Every candidate column has the same value in every cell -- this is an isolated "
        "population, not an annotated one.",
        "No usable author column: Lineage does not vary, it is a single value throughout.",
    ):
        assert verdict(checks, phrasing), phrasing


def test_constant_case_fails_when_a_constant_column_is_the_answer():
    checks = answer_checks("constant-columns")
    assert not verdict(checks, "The author cell-type column is `Cell.class`, which is "
                               "constant for this dataset.")


def test_hierarchy_case_needs_all_three_levels():
    checks = answer_checks("annotation-hierarchy")
    assert verdict(checks, "celltype.l1 (8), celltype.l2 (20), celltype.l3 (31) -- three "
                           "nested levels.")
    assert not verdict(checks, "The author annotation is celltype.l3, with 31 labels.")


def test_composition_case_fails_a_second_remote_read():
    checks = load("read-obs-once")
    good = ("h5ad-obs https://datasets.cellxgene.cziscience.com/x.h5ad --out obs.parquet "
            "&& h5ad-obs obs.parquet --profile text")
    bad = ("h5ad-obs https://datasets.cellxgene.cziscience.com/x.h5ad --profile text && "
           "h5ad-obs https://datasets.cellxgene.cziscience.com/x.h5ad --out obs.parquet")
    answer = "BICCN_class_label (5 labels) and BICCN_cluster_label (33 labels)."
    assert verdict(checks, answer, commands=good)
    assert not verdict(checks, answer, commands=bad)


def test_tool_choice_case_fails_on_a_picker_dispatch():
    checks = load("standardised-request-does-not-trigger")
    answer = "GABAergic neuron 812, glutamatergic neuron 799, ... (1,679 cells)."
    assert verdict(checks, answer, commands="h5ad-obs https://x/y.h5ad --out obs.parquet")
    calls = [{"name": "Bash", "input": {"command": "h5ad-obs https://x/y.h5ad --out o.parquet"}},
             {"name": "Task", "input": {"subagent_type": "author-celltype-picker"}}]
    assert not all(r.passed for r in grade(Run(answer=answer, tool_calls=calls), checks))


# --- the runner's plugin guard ----------------------------------------------

def test_plugin_list_is_parsed_into_name_version_scope(monkeypatch):
    """Scope is the part that matters and the obvious check drops it: the cases
    run in a temp directory, so a project- or local-scope install is invisible
    to them and must not satisfy the guard."""
    import subprocess as sp

    import runner

    bullet = "\u276f"  # the glyph the CLI actually prints, kept out of the source
    listing = "\n".join([
        "Installed plugins:", "",
        f"  {bullet} author-celltype-columns@atlas-skills",
        "    Version: 0.1.0", "    Scope: user", "    Status: enabled", "",
        f"  {bullet} author-celltype-columns@atlas-skills",
        "    Version: 0.2.0", "    Scope: local", "    Status: enabled", ""])
    monkeypatch.setattr(sp, "run", lambda *a, **k: sp.CompletedProcess(a, 0, listing, ""))
    rows = runner.installed_plugins()
    assert [(r["version"], r["scope"]) for r in rows] == [("0.1.0", "user"), ("0.2.0", "local")]


def test_guard_rejects_a_local_only_install(monkeypatch):
    import runner

    monkeypatch.setattr(runner, "installed_plugins", lambda: [
        {"name": "author-celltype-columns@atlas-skills", "version": "0.2.0", "scope": "local"}])
    with pytest.raises(SystemExit) as exc:
        runner.check_plugin_installed()
    assert "temp directory" in str(exc.value)


def test_guard_rejects_a_stale_user_install(monkeypatch):
    """A SKILL.md edit needs a tag and a marketplace update before it reaches
    these cases. Silently testing the previous release is the trap."""
    import runner

    monkeypatch.setattr(runner, "installed_plugins", lambda: [
        {"name": "author-celltype-columns@atlas-skills", "version": "0.1.0", "scope": "user"}])
    with pytest.raises(SystemExit) as exc:
        runner.check_plugin_installed()
    assert runner.EXPECTED_PLUGIN_VERSION in str(exc.value)


def test_guard_accepts_the_expected_user_install(monkeypatch):
    import runner

    monkeypatch.setattr(runner, "installed_plugins", lambda: [
        {"name": "author-celltype-columns@atlas-skills",
         "version": runner.EXPECTED_PLUGIN_VERSION, "scope": "user"}])
    runner.check_plugin_installed()


# --- the committed profile fixtures -----------------------------------------

def test_every_manifest_dataset_has_a_committed_profile():
    """Re-scoring the picker must need no network. A missing fixture silently
    turns an offline re-score into a 1.5 GB fetch."""
    import json as _json

    import benchmark

    prov = _json.loads(benchmark.PROVENANCE.read_text())
    have = {p.stem for p in benchmark.PROFILES.glob("*.txt")}
    assert len(have) == prov["n_datasets"] == 73
    # The one absent dataset is absent for a recorded reason, not by accident.
    assert set(prov["missing"]) & set(prov["missing"])
    for dsid, reason in prov["missing"].items():
        assert dsid not in have
        assert len(reason) > 20, f"{dsid} is missing with no explanation"


def test_provenance_records_what_captured_the_profiles():
    """A profile with no record of which reader version produced it cannot be
    checked for staleness, and the format is exactly what the picker sees."""
    import json as _json

    import benchmark

    prov = _json.loads(benchmark.PROVENANCE.read_text())
    assert prov["captured_by"].startswith("h5ad-obs ")
    assert prov["captured"] and prov["commit"]
    for dsid, entry in prov["profiles"].items():
        path = benchmark.PROFILES / f"{dsid}.txt"
        assert path.stat().st_size == entry["bytes"], f"{dsid} changed since capture"


def test_profiles_carry_no_picking_instructions():
    """The rules live in the picker agent. A fixture that smuggled guidance in
    would make the benchmark score the prompt, not the agent."""
    import benchmark

    for path in benchmark.PROFILES.glob("*.txt"):
        text = path.read_text().lower()
        for word in ("you are", "do not pick", "rule ", "author-provided"):
            assert word not in text, f"{path.name} contains instruction text: {word!r}"


# --- pulling the picks out of a reply ---------------------------------------

@pytest.mark.parametrize(("label", "reply", "expected"), [
    ("bare", '{"picks": ["a"], "reasoning": "x"}', ["a"]),
    ("fenced", '```json\n{"picks": ["a"], "reasoning": "x"}\n```', ["a"]),
    ("trailing prose", '{"picks": ["a"], "reasoning": "x"}\n\nLet me know if you '
                       'want the counts.', ["a"]),
    ("preamble", 'Here you go:\n{"picks": [], "reasoning": "all constant"}', []),
    ("earlier object", '{"note": 1}\n{"picks": ["b"], "reasoning": "y"}', ["b"]),
])
def test_picks_are_recovered_from_an_untidy_reply(label, reply, expected):
    """A formatting slip is not the behaviour under test. The first attempt used
    a greedy brace-to-brace regex, which spans from the first brace to the last
    in the whole reply -- so a single trailing line swallowed the match and the
    parse failed. That silently cost two datasets on the first full run."""
    import benchmark

    assert benchmark._extract_picks(reply)["picks"] == expected, label


def test_a_reply_with_no_picks_object_is_not_invented():
    import benchmark

    assert benchmark._extract_picks("I could not determine the columns.") is None
    assert benchmark._extract_picks('{"reasoning": "no picks key here"}') is None


def test_every_curated_column_exists_in_the_dataset():
    """The gold set names obs columns; if one is not there, no picker can ever
    match it and the dataset's score is capped below 1 for no reason. Four such
    names were found on the first full run -- all capitalisation slips, now
    corrected on read in `celltype_column_eval.curation`. This fails if another
    appears, in the curation or after a profile regeneration."""
    import sys

    sys.path.insert(0, str(pathlib.Path(__file__).parent.parent
                           / "packages/celltype-column-eval/src"))
    import benchmark
    from celltype_column_eval import full, parse_curation

    curation = parse_curation()
    missing = []
    for dsid in full():
        path = benchmark.PROFILES / f"{dsid}.txt"
        if not path.exists() or dsid not in curation:
            continue
        present = {line.split(" | ")[0]
                   for line in path.read_text().splitlines()[4:] if " | " in line}
        for name in curation[dsid]["columns"]:
            if name not in present:
                near = [c for c in present if c.lower() == name.lower()]
                missing.append(f"{dsid} {name!r}"
                               + (f" (obs has {near[0]!r})" if near else " (no near match)"))
    assert not missing, "curated columns absent from obs:\n  " + "\n  ".join(missing)


def test_naming_the_standardised_field_as_rejected_is_not_penalised():
    """The first version of this check was a bare `answer_not_matches` on the
    column name, and it failed the best answer the skill produced in its first
    real run -- one that listed what it had rejected and why, which SKILL.md
    explicitly asks for. It was the one rejection check with no both-directions
    test, which is exactly why it slipped through."""
    checks = answer_checks("read-obs-once")
    good = ("Author columns: BICCN_class_label (5) and BICCN_cluster_label (33). "
            "Not picked, and worth naming so you can check the call: `cre` is the "
            "transgenic driver line; `cell_type`/`cell_type_ontology_term_id` are the "
            "portal's standardised annotation, not the authors'.")
    assert verdict(checks, good)


def test_picking_the_standardised_field_still_fails():
    checks = answer_checks("read-obs-once")
    bad = ("The author cell-type columns are BICCN_class_label, BICCN_cluster_label "
           "and cell_type_ontology_term_id.")
    assert not verdict(checks, bad)
    assert not verdict(checks, "I picked cell_type_ontology_term_id and "
                               "BICCN_class_label and BICCN_cluster_label.")
