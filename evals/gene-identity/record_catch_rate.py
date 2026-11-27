#!/usr/bin/env python3
"""How much of what can go wrong in a .gene-records.json does `gene-id check` catch?

    python3 evals/gene-identity/record_catch_rate.py          # the table
    python3 evals/gene-identity/record_catch_rate.py --json

Offline and free. A clean set of records (one per outcome, a higher-taxon
GENE record among them) is checked against a fixed world: what NodeNorm
says about each gene, NCBI Taxonomy lineages, and the resolve log. Each
mutation class is applied to every record it fits, one at a time, and the
rate is the share of mutated files the check flags.

- **catchable** classes must be caught every time;
- **controls** are changes that are fine (a gene of a descendant species
  under a higher taxon, a reworded rationale) and must never be flagged;
- **not catchable** classes are the judgement the check cannot make: a real,
  looked-up gene whose ID and official symbol agree, but which is not the
  gene the source means (Dio1 for "D1"). They are measured so the limit is
  stated, not hidden; the smoke evals and the benchmark cover them.

Needs gene-identity installed (the package venv, or CI's environment).
"""
from __future__ import annotations

import argparse
import copy
import json
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path

from gene_identity import check

# ── The world ────────────────────────────────────────────────────────────────

M, R, H = "NCBITaxon:10090", "NCBITaxon:10116", "NCBITaxon:9606"
MURINAE = "NCBITaxon:39107"

#: NodeNorm. A replaced ID answers with its successor; an unknown one, nothing.
NODENORM = {
    "NCBIGene:13488": ("Drd1", M), "NCBIGene:13370": ("Dio1", M), "NCBIGene:13489": ("Drd2", M),
    "NCBIGene:1812": ("DRD1", H), "NCBIGene:83839": ("Calb1", R), "NCBIGene:12307": ("Calb1", M),
    "NCBIGene:20604": ("Sst", M), "NCBIGene:234725": ("Grhl3", M), "NCBIGene:52897": ("Rbfox3", M),
}
REPLACED = {"NCBIGene:99000001": "NCBIGene:13488"}
LINEAGE = {
    M: [M, "NCBITaxon:862507", MURINAE, "NCBITaxon:9989"],
    R: [R, "NCBITaxon:10114", MURINAE, "NCBITaxon:9989"],
    H: [H, "NCBITaxon:9605", "NCBITaxon:9443"],
}
#: What `gene-id resolve` returned in this session. Drd2 was never looked up.
RESOLVED = sorted(set(NODENORM) - {"NCBIGene:13489"})
#: The one class only the provenance check can catch. Every other class is
#: measured a second time with provenance off, so a catch can't be the resolve
#: log doing another check's job (a made-up ID is also never looked up).
PROVENANCE_ONLY = {"never_looked_up"}


def lookup_genes(ids: list[str]) -> dict[str, dict | None]:
    out: dict[str, dict | None] = {}
    for i in ids:
        if i in NODENORM:
            label, taxon = NODENORM[i]
            out[i] = {"ncbi_gene_id": i, "label": label, "taxon": taxon}
        elif i in REPLACED:
            label, taxon = NODENORM[REPLACED[i]]
            out[i] = {"ncbi_gene_id": REPLACED[i], "label": label, "taxon": taxon}
        else:
            out[i] = None
    return out


def _gene(name, gid, symbol, taxon=M, gene_taxon=M, **kw):
    return {"name": name, "taxon": taxon, "outcome": "GENE", "ncbi_gene_id": gid,
            "symbol": symbol, "gene_taxon": gene_taxon, "method": "PAPER_DEFINITION",
            "antibody": None, "evidence": "...", "rationale": "from the quote", **kw}


CLEAN = [
    _gene("D1", "NCBIGene:13488", "Drd1"),
    _gene("CB", "NCBIGene:83839", "Calb1", taxon=MURINAE, gene_taxon=R),
    _gene("NeuN", "NCBIGene:52897", "Rbfox3", antibody="NeuN", method="ANTIBODY_TARGET"),
    {"name": "SOM", "taxon": M, "outcome": "UNRESOLVED", "kind": "AMBIGUOUS",
     "claimants": [{"ncbi_gene_id": "NCBIGene:20604", "symbol": "Sst"},
                   {"ncbi_gene_id": "NCBIGene:234725", "symbol": "Grhl3"}],
     "rationale": "no context"},
    {"name": "CaMKII", "taxon": M, "outcome": "NO_SINGLE_GENE", "kind": "GENE_FAMILY",
     "rationale": "four genes"},
    {"name": "SP", "taxon": M, "outcome": "NOT_A_GENE_PRODUCT", "kind": "NON_GENE_TERM",
     "rationale": "stratum pyramidale"},
]

# ── Mutations: record -> mutated record, or None when the class doesn't apply ─

Mutation = Callable[[dict], dict | None]


def _on_gene(f: Callable[[dict], None]) -> Mutation:
    def m(rec):
        if rec["outcome"] != "GENE":
            return None
        out = copy.deepcopy(rec)
        f(out)
        return out
    return m


def _on_ambiguous(f: Callable[[dict], None]) -> Mutation:
    def m(rec):
        if rec.get("kind") != "AMBIGUOUS":
            return None
        out = copy.deepcopy(rec)
        f(out)
        return out
    return m


def _set(**kw) -> Callable[[dict], None]:
    return lambda r: r.update(kw)


def _other_id(r):        # a real gene's ID; the symbol left as it was
    r["ncbi_gene_id"] = "NCBIGene:13370" if r["ncbi_gene_id"] != "NCBIGene:13370" else "NCBIGene:13488"


def _human(r):           # the human orthologue, internally consistent
    r.update(ncbi_gene_id="NCBIGene:1812", symbol="DRD1", gene_taxon=H)


def _human_claims_taxon(r):   # the human orthologue, gene_taxon copied from the record
    r.update(ncbi_gene_id="NCBIGene:1812", symbol="DRD1", gene_taxon=r["taxon"])


def _uppercase(r):
    if r["symbol"].upper() == r["symbol"]:
        r["symbol"] = r["symbol"].lower()
    else:
        r["symbol"] = r["symbol"].upper()


def _claimant_symbol(r):
    r["claimants"][0]["symbol"] = r["name"]


def _claimant_made_up(r):
    r["claimants"][1]["ncbi_gene_id"] = "NCBIGene:424242424"


def _dio1(r):            # real, looked up, consistent: the wrong gene for "D1"
    if r["name"] != "D1":
        raise LookupError
    r.update(ncbi_gene_id="NCBIGene:13370", symbol="Dio1")


def _never_looked_up(r):     # a real, consistent gene the lookup never returned
    r.update(ncbi_gene_id="NCBIGene:13489", symbol="Drd2")


def _not_applicable_unless(pred: Callable[[dict], bool], m: Mutation) -> Mutation:
    def g(rec):
        return m(rec) if pred(rec) else None
    return g


CATCHABLE: dict[str, Mutation] = {
    # What the world knows.
    "wrong_id": _on_gene(_other_id),
    "made_up_id": _on_gene(_set(ncbi_gene_id="NCBIGene:424242424")),
    "retired_id": _on_gene(_set(ncbi_gene_id="NCBIGene:99000001")),
    "source_wording_as_symbol": _on_gene(lambda r: r.update(symbol=r["name"])),
    "symbol_in_another_case": _on_gene(_uppercase),
    "wrong_gene_taxon": _on_gene(lambda r: r.update(
        gene_taxon=H if r["gene_taxon"] != H else M)),
    "gene_of_another_species": _not_applicable_unless(
        lambda r: r["taxon"] == M, _on_gene(_human)),
    "gene_of_another_species_claiming_the_taxon": _not_applicable_unless(
        lambda r: r["taxon"] == M, _on_gene(_human_claims_taxon)),
    "claimant_symbol_is_source_wording": _on_ambiguous(_claimant_symbol),
    "claimant_made_up": _on_ambiguous(_claimant_made_up),
    "never_looked_up": _on_gene(_never_looked_up),
    # Shape (the schema, run first).
    "gene_without_id": _on_gene(_set(ncbi_gene_id=None)),
    "kind_on_gene": _on_gene(_set(kind="GENE_FAMILY")),
    "bad_outcome": lambda r: {**copy.deepcopy(r), "outcome": "PROBABLY_GENE"},
    "claimants_on_resolved": _on_gene(_set(claimants=[
        {"ncbi_gene_id": "NCBIGene:20604", "symbol": "Sst"},
        {"ncbi_gene_id": "NCBIGene:234725", "symbol": "Grhl3"}])),
    "id_on_family": lambda r: ({**copy.deepcopy(r), "ncbi_gene_id": "NCBIGene:12307"}
                               if r["outcome"] == "NO_SINGLE_GENE" else None),
}

CONTROLS: dict[str, Mutation] = {
    "unmutated": lambda r: copy.deepcopy(r),
    "reworded_rationale": lambda r: {**copy.deepcopy(r), "rationale": "Reworded, still right."},
    "record_taxon_widened_to_murinae": _not_applicable_unless(
        lambda r: r["taxon"] == M, _on_gene(_set(taxon=MURINAE))),
}

NOT_CATCHABLE: dict[str, Mutation] = {
    "wrong_gene_looked_up_and_consistent": lambda r: (
        _on_gene(_dio1)(r) if r["name"] == "D1" else None),
}


# ── Measurement ──────────────────────────────────────────────────────────────


def _store(directory: Path) -> check.Store:
    check.log_resolved([{"name": "x", "gene": {"ncbi_gene_id": i}} for i in RESOLVED],
                       directory=directory)
    return check.Store(directory=directory, lookup_genes=lookup_genes,
                       lookup_lineage=lambda t: LINEAGE.get(t, []))


def measure() -> dict:
    with tempfile.TemporaryDirectory() as d:
        store = _store(Path(d))
        clean_problems, clean_unchecked = check.check(CLEAN, store)
        out = {"unmutated_file": {"problems": clean_problems, "unchecked": clean_unchecked},
               "classes": {}}
        for group, classes in (("catchable", CATCHABLE), ("control", CONTROLS),
                               ("not_catchable", NOT_CATCHABLE)):
            for name, mutate in classes.items():
                tried = caught = caught_alone = 0
                unchecked = 0
                examples = []
                for i, rec in enumerate(CLEAN):
                    mutated = mutate(rec)
                    if mutated is None:
                        continue
                    records = [*CLEAN[:i], mutated, *CLEAN[i + 1:]]
                    problems, unc = check.check(records, store)
                    alone, _ = check.check(records, store, provenance=False)
                    tried += 1
                    caught += bool(problems)
                    caught_alone += bool(alone)
                    unchecked += bool(unc)
                    if problems and len(examples) < 1:
                        examples.append(problems[0])
                out["classes"][name] = {"group": group, "tried": tried, "caught": caught,
                                        "rate": caught / tried if tried else None,
                                        "caught_without_provenance": caught_alone,
                                        "unchecked": unchecked, "example": examples[0] if examples else None}
        return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    result = measure()
    if args.json:
        print(json.dumps(result, indent=2))
        return 0
    print(f"{'class':<44} {'group':<14} {'caught':>9}  {'rate':>4}  without provenance")
    for name, c in result["classes"].items():
        rate = "n/a" if c["rate"] is None else f"{c['rate']:.0%}"
        print(f"{name:<44} {c['group']:<14} {c['caught']:>4}/{c['tried']:<4}  {rate:>4}  "
              f"{c['caught_without_provenance']}/{c['tried']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
