"""The record schema: one valid record per outcome, and each rule broken once."""

from __future__ import annotations

import copy
import json

import pytest
from gene_identity import cli, records

GENE = {
    "name": "CB", "taxon": "NCBITaxon:10116", "outcome": "GENE",
    "ncbi_gene_id": "NCBIGene:83839", "symbol": "Calb1", "gene_taxon": "NCBITaxon:10116",
    "method": "PAPER_DEFINITION", "kind": None, "antibody": None,
    "evidence": '"... CB, calbindin-D28k ..."',
    "rationale": "Paper defines CB as calbindin-D28k; claimants were Calb1 and Ctsb.",
    "claimants": [],
}
ANTIBODY = {
    "name": "NeuN", "taxon": "NCBITaxon:10090", "outcome": "GENE",
    "ncbi_gene_id": "NCBIGene:52897", "symbol": "Rbfox3", "gene_taxon": "NCBITaxon:10090",
    "method": "ANTIBODY_TARGET", "antibody": "NeuN",
    "rationale": "NeuN antibody (A60) detects Rbfox3.",
}
FAMILY = {
    "name": "CaMKII", "taxon": "NCBITaxon:10090", "outcome": "NO_SINGLE_GENE",
    "kind": "GENE_FAMILY", "rationale": "Four genes (Camk2a/b/d/g); no subunit named.",
}
GLYCOFORM = {
    "name": "PSA-NCAM", "taxon": "NCBITaxon:10090", "outcome": "NO_SINGLE_GENE",
    "kind": "GLYCOFORM", "antibody": "PSA-NCAM", "rationale": "Polysialylated NCAM epitope.",
}
REGION = {
    "name": "SP", "taxon": "NCBITaxon:10090", "outcome": "NOT_A_GENE_PRODUCT",
    "kind": "NON_GENE_TERM", "ncbi_gene_id": None, "symbol": None, "gene_taxon": None,
    "method": None, "evidence": '"... in stratum pyramidale (SP) ..."',
    "rationale": "SP is the stratum pyramidale here, not substance P.",
}
AMBIGUOUS = {
    "name": "SOM", "taxon": "NCBITaxon:10090", "outcome": "UNRESOLVED", "kind": "AMBIGUOUS",
    "claimants": [{"ncbi_gene_id": "NCBIGene:20604", "symbol": "Sst"},
                  {"ncbi_gene_id": "NCBIGene:234725", "symbol": "Grhl3"}],
    "rationale": "No evidence given and the source's field is unknown.",
}
LOOKUP_FAILED = {
    "name": "PV", "taxon": "NCBITaxon:10090", "outcome": "UNRESOLVED", "kind": "LOOKUP_FAILED",
    "rationale": "gene-id resolve exited 1: Translator unreachable.",
}
VALID = [GENE, ANTIBODY, FAMILY, GLYCOFORM, REGION, AMBIGUOUS, LOOKUP_FAILED]


def _with(rec: dict, **changes) -> dict:
    out = copy.deepcopy(rec)
    for k, v in changes.items():
        if v is _DROP:
            out.pop(k, None)
        else:
            out[k] = v
    return out


_DROP = object()


def test_every_outcome_has_a_valid_record():
    assert records.validate(VALID) == []
    assert records.validate([]) == []


@pytest.mark.parametrize("rec, fragment", [
    # The file is an array of records.
    (None, None),
    # Required everywhere.
    (_with(GENE, name=_DROP), "'name' is required"),
    (_with(GENE, taxon=_DROP), "'taxon' is required"),
    (_with(GENE, rationale=""), "rationale"),
    (_with(GENE, taxon="10116"), "taxon"),
    (_with(GENE, taxon="NCBITaxon:rat"), "taxon"),
    # Enums.
    (_with(GENE, outcome="MAYBE"), "outcome"),
    (_with(GENE, method="FROM_MEMORY"), "method"),
    (_with(FAMILY, kind="COMPLEX"), "kind"),
    # A GENE record names one gene, completely.
    (_with(GENE, ncbi_gene_id=None), "ncbi_gene_id"),
    (_with(GENE, ncbi_gene_id="NCBIGene:Calb1"), "ncbi_gene_id"),
    (_with(GENE, ncbi_gene_id="HGNC:1434"), "ncbi_gene_id"),
    (_with(GENE, symbol=_DROP), "'symbol' is required"),
    (_with(GENE, gene_taxon=_DROP), "'gene_taxon' is required"),
    (_with(GENE, method=_DROP), "'method' is required"),
    (_with(GENE, kind="GENE_FAMILY"), "kind"),
    (_with(GENE, claimants=AMBIGUOUS["claimants"]), "claimants"),
    # Anything else names no gene.
    (_with(FAMILY, ncbi_gene_id="NCBIGene:12322"), "ncbi_gene_id"),
    (_with(REGION, symbol="Tac1"), "symbol"),
    (_with(FAMILY, method="UNIQUE_SYNONYM"), "method"),
    (_with(FAMILY, kind=_DROP), "'kind' is required"),
    # Each outcome has its own kinds.
    (_with(FAMILY, kind="NON_GENE_TERM"), "kind"),
    (_with(REGION, kind="GENE_FAMILY"), "kind"),
    (_with(AMBIGUOUS, kind="GENE_FAMILY"), "kind"),
    # Claimants: AMBIGUOUS needs two or more, nothing else carries them.
    (_with(AMBIGUOUS, claimants=_DROP), "'claimants' is required"),
    (_with(AMBIGUOUS, claimants=AMBIGUOUS["claimants"][:1]), "at least two"),
    (_with(AMBIGUOUS, claimants=[{"ncbi_gene_id": "NCBIGene:20604"}] * 2), "symbol"),
    (_with(LOOKUP_FAILED, claimants=AMBIGUOUS["claimants"]), "claimants"),
    # No fields outside the record.
    (_with(GENE, confidence=0.9), "confidence"),
])
def test_each_rule_is_enforced(rec, fragment):
    if rec is None:
        problems = records.validate({"records": VALID})
        assert problems and problems[0].startswith("(file)")
        return
    problems = records.validate([GENE, rec])
    assert problems, f"accepted: {rec}"
    # Errors name the record by index and by name, so a fix can find it.
    prefix = f"[1] ({rec['name']})" if "name" in rec else "[1]"
    assert all(p.startswith(prefix) for p in problems), problems
    assert any(fragment in p for p in problems), problems


def test_required_message_says_whether_it_depends_on_the_outcome():
    assert records.validate([_with(GENE, taxon=_DROP)]) == ["[0] (CB): 'taxon' is required"]
    assert records.validate([_with(GENE, symbol=_DROP)]) == [
        "[0] (CB): 'symbol' is required for this outcome"]


def test_null_rule_message_says_why():
    [p] = records.validate([_with(FAMILY, ncbi_gene_id="NCBIGene:12322")])
    assert p == "[0] (CaMKII).ncbi_gene_id: must be null or absent for this outcome (got 'NCBIGene:12322')"


# ── CLI ──────────────────────────────────────────────────────────────────────


def test_cli_validate_ok(tmp_path, capsys):
    f = tmp_path / "x.gene-records.json"
    f.write_text(json.dumps(VALID))
    assert cli.main(["validate", str(f)]) == 0
    assert "7 record(s), valid" in capsys.readouterr().out


def test_cli_validate_problems_exit_2(tmp_path, capsys):
    f = tmp_path / "x.gene-records.json"
    f.write_text(json.dumps([_with(GENE, ncbi_gene_id=None)]))
    assert cli.main(["validate", str(f)]) == 2
    assert "[0] (CB).ncbi_gene_id" in capsys.readouterr().err


@pytest.mark.parametrize("content", [None, "{not json"])
def test_cli_validate_unreadable_exit_1(tmp_path, content):
    f = tmp_path / "x.gene-records.json"
    if content is not None:
        f.write_text(content)
    assert cli.main(["validate", str(f)]) == 1


def test_cli_schema_prints_the_packaged_schema(capsys):
    assert cli.main(["schema"]) == 0
    assert json.loads(capsys.readouterr().out) == records.schema()
