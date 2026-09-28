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
