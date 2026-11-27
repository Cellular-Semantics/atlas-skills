"""The gic benchmark's case files, scoring and run log. Offline and free."""

from __future__ import annotations

import hashlib
import json
import re

import gic_benchmark as gb
import pytest

CASES = gb.load_cases()
ANSWERS = gb.load_answers()


def test_every_case_has_an_answer_and_no_answer_is_orphaned():
    assert len(CASES) == 13
    assert set(CASES) == set(ANSWERS)


@pytest.mark.parametrize("cid", sorted(CASES))
def test_case_is_input_only(cid):
    """The agent sees the case file: no answer may leak into it."""
    case = CASES[cid]
    assert set(case) <= {"id", "name", "taxon", "title", "evidence"}
    assert re.fullmatch(r"NCBITaxon:[0-9]+", case["taxon"])
    blob = json.dumps(case)
    for a in ANSWERS[cid]["accept"]:
        assert a["ncbi_gene_id"] not in blob


@pytest.mark.parametrize("cid", sorted(ANSWERS))
def test_answer_is_well_formed(cid):
    a = ANSWERS[cid]
    assert a["outcome"] in ("GENE", "NO_SINGLE_GENE", "NOT_A_GENE_PRODUCT", "UNRESOLVED")
    if a["outcome"] == "GENE":
        assert a["accept"] and a["kind"] is None
        assert all(re.fullmatch(r"NCBIGene:[0-9]+", x["ncbi_gene_id"]) for x in a["accept"])
    else:
        assert a["accept"] == [] and a["kind"]


def test_provenance_names_every_converted_file():
    prov = json.loads((gb.HERE / "PROVENANCE.json").read_text())
    assert re.fullmatch(r"[0-9a-f]{40}", prov["commit"])
    names = {k.rsplit("/", 1)[-1].removesuffix(".yaml") for k in prov["files_sha256"]}
    assert names == set(CASES) | {"answers"}


def test_quote_variant_drops_the_title_and_no_variant_shows_the_storage_key():
    case = CASES["gic-01"]
    assert "title" not in gb.agent_input(case, "quote")
    assert gb.agent_input(case, "quote-title")["title"] == case["title"]
    for v in gb.AGENT_VARIANTS:
        shown = gb.agent_input(case, v)
        assert "id" not in shown and "quote_key" not in shown["evidence"]


# ── Scoring ──────────────────────────────────────────────────────────────────

GENE_ANSWER = {"outcome": "GENE", "kind": None,
               "accept": [{"ncbi_gene_id": "NCBIGene:243764", "symbol": "Chrm2"},
                          {"ncbi_gene_id": "NCBIGene:81645", "symbol": "Chrm2"}]}
FAMILY_ANSWER = {"outcome": "NO_SINGLE_GENE", "kind": "GENE_FAMILY", "accept": []}


@pytest.mark.parametrize("record, answer, passed", [
    ({"outcome": "GENE", "ncbi_gene_id": "NCBIGene:81645"}, GENE_ANSWER, True),   # either species
    ({"outcome": "GENE", "ncbi_gene_id": "NCBIGene:1"}, GENE_ANSWER, False),
    ({"outcome": "UNRESOLVED", "kind": "AMBIGUOUS"}, GENE_ANSWER, False),
    ({"outcome": "NO_SINGLE_GENE", "kind": "GENE_FAMILY"}, FAMILY_ANSWER, True),
    ({"outcome": "NO_SINGLE_GENE", "kind": "PTM_STATE"}, FAMILY_ANSWER, False),
    ({"outcome": "GENE", "ncbi_gene_id": "NCBIGene:14405"}, FAMILY_ANSWER, False),
    (None, FAMILY_ANSWER, False),
    # NLM-Gene expects no kind (it doesn't say family vs complex): outcome only.
    ({"outcome": "NO_SINGLE_GENE", "kind": "PTM_STATE"}, {**FAMILY_ANSWER, "kind": None}, True),
    ({"outcome": "UNRESOLVED", "kind": "AMBIGUOUS"}, {**FAMILY_ANSWER, "kind": None}, False),
])
def test_score(record, answer, passed):
    assert gb.score(record, answer)[0] is passed


GENERIC_ANSWER = {**GENE_ANSWER, "generic": True}


def test_generic_mention_accepts_no_single_gene_like_the_package_scorer():
    """The driver and gene_identity_eval.metrics must agree (they once did not)."""
    from gene_identity_eval import metrics

    refuse = {"outcome": "NO_SINGLE_GENE", "kind": "GENE_FAMILY"}
    for record, answer in [
        (refuse, GENERIC_ANSWER), (refuse, GENE_ANSWER),
        ({"outcome": "GENE", "ncbi_gene_id": "NCBIGene:1"}, GENERIC_ANSWER),
        ({"outcome": "UNRESOLVED", "kind": "AMBIGUOUS"}, GENERIC_ANSWER),
        ({"outcome": "GENE", "ncbi_gene_id": "NCBIGene:81645"}, GENERIC_ANSWER),
    ]:
        assert gb.score(record, answer) == metrics.score(record, answer)
    assert gb.score(refuse, GENERIC_ANSWER)[0] is True
    assert gb.score(refuse, GENE_ANSWER)[0] is False


def test_method_and_rationale_are_not_scored():
    rec = {"outcome": "GENE", "ncbi_gene_id": "NCBIGene:243764", "method": "WHATEVER",
           "rationale": ""}
    assert gb.score(rec, GENE_ANSWER)[0]


def test_baseline_is_frozen_at_3_of_13():
    """The lookup alone: the floor. A change here means the cases or the
    scoring moved, and every logged run needs re-reading."""
    passed = {cid for cid, a in ANSWERS.items() if gb.score(gb.baseline_record(a), a)[0]}
    assert passed == {"gic-07", "gic-11", "gic-13"}


@pytest.mark.parametrize("text, expected", [
    ('Done.\n```json\n{"outcome": "GENE", "ncbi_gene_id": "NCBIGene:1"}\n```',
     {"outcome": "GENE", "ncbi_gene_id": "NCBIGene:1"}),
    ('```json\n{"outcome": "UNRESOLVED"}\n```\nthen\n```json\n{"outcome": "GENE"}\n```',
     {"outcome": "GENE"}),                                     # the last block wins
    ('```json\n[{"outcome": "GENE"}]\n```', {"outcome": "GENE"}),
    ('{"outcome": "NOT_A_GENE_PRODUCT"}', {"outcome": "NOT_A_GENE_PRODUCT"}),
    ("no record here", None),
    ('```json\n{broken\n```', None),
])
def test_extract_record(text, expected):
    assert gb.extract_record(text) == expected


def _tool(name, inp):
    return {"type": "assistant", "message": {"content": [
        {"type": "tool_use", "name": name, "input": inp}]}}


def test_a_run_that_reads_the_answers_is_voided():
    events = [_tool("Bash", {"command": "gene-id resolve --taxon NCBITaxon:10090 SOM"}),
              _tool("Read", {"file_path": "/x/atlas-skills/evals/gene-identity/answers.json"})]
    hits = gb.touched_forbidden(events)
    assert len(hits) == 1 and hits[0].startswith("Read")
    assert gb.touched_forbidden(events[:1]) == []


def test_summarise_counts_only_scored_cases():
    rows = [{"id": "a", "passed": True, "cost_usd": 0.1},
            {"id": "b", "passed": False, "cost_usd": 0.2},
            {"id": "c", "voided": True, "cost_usd": 0.1},
            {"id": "d", "error": "timed out"}]
    s = gb.summarise(rows)
    assert (s["n_scored"], s["passed"], s["accuracy"]) == (2, 1, 0.5)
    assert s["voided"] == ["c"] and s["errors"] == ["d"] and s["cost_usd"] == 0.4


# ── Run log ──────────────────────────────────────────────────────────────────


def test_committed_runs_are_complete():
    for f in sorted(gb.RUNS.glob("*.json")):
        run = json.loads(f.read_text())
        assert set(run) >= gb.REQUIRED_RUN_KEYS, f.name
        assert run["variant"] in gb.AGENT_VARIANTS
        assert run.get("set", "gic") in ("gic", "nlm-gene")
        if run.get("set") == "nlm-gene":
            assert run["tier"] and "metrics" in run, f.name


def test_write_run_never_overwrites(tmp_path, monkeypatch):
    monkeypatch.setattr(gb, "RUNS", tmp_path)
    monkeypatch.setattr(gb, "INDEX", tmp_path / "README.md")
    rec = {"date": "2026-11-27", "variant": "quote", "provenance": {"commit": "abc"},
           "passed": 1, "n_scored": 1, "accuracy": 1.0, "voided": [], "errors": [],
           "cost_usd": 0.1}
    a, b = gb.write_run(rec), gb.write_run(rec)
    assert a != b and a.name == "2026-11-27-quote-abc.json" and b.name == "2026-11-27-quote-abc-2.json"
    assert hashlib.sha256(a.read_bytes()).digest() == hashlib.sha256(b.read_bytes()).digest()
    assert (tmp_path / "README.md").read_text().count("| quote |") == 2
