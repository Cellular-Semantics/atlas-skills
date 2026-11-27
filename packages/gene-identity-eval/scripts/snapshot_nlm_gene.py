#!/usr/bin/env python3
"""Rebuild the committed NLM-Gene snapshot. Dev-only, network, ~15 minutes.

    python scripts/snapshot_nlm_gene.py --work /tmp/nlm            # download, build, baseline
    python scripts/snapshot_nlm_gene.py --work /tmp/nlm --tiers-only

Needs gene-identity installed beside this package (its Translator clients and
the lookup are what the baseline *is*). Writes, under
``src/gene_identity_eval/data/nlm_gene/``:

- ``cases.jsonl``: one case per test-split mention (see ``nlm_gene.py``), with
  the lookup's own answer as ``resolver_baseline``;
- ``tiers.json``: the scored tiers, a seeded stratified sample;
- ``SOURCE.json``: the Zenodo record, checksums of every file read, the
  Translator versions, and what was excluded and why.

Only the test split is used for scoring; the train split is left for
iterating on SKILL.md.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import urllib.request
import zipfile
from collections import Counter
from datetime import date
from pathlib import Path

from gene_identity import resolve, translator
from gene_identity_eval import metrics, nlm_gene

RECORD = "https://zenodo.org/api/records/5089049"
FILES = ("NLM-Gene-Corpus.zip", "Pmidlist.Test.txt", "Pmidlist.Train.txt")
OUT = Path(__file__).resolve().parents[1] / "src" / "gene_identity_eval" / "data" / "nlm_gene"

#: The scored tier. Every hard case, a capped sample of families and a control
#: sample of cases the lookup already gets right. Changing this after results
#: are published needs a new tier (docs/evals.md rule 6).
TIERS = {
    "l4": {"seed": 20261127,
           "caps": {"lookup_wrong": 40, "lookup_ambiguous": 40, "lookup_no_match": 40,
                    "family": 30, "easy": 30}},
}


def _get_json(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=60) as r:
        return json.loads(r.read())


def download(work: Path) -> dict:
    meta = _get_json(RECORD)
    by_key = {f["key"]: f for f in meta["files"]}
    files = {}
    for name in FILES:
        f = by_key[name]
        path = work / name
        if not path.exists():
            with urllib.request.urlopen(f["links"]["self"], timeout=120) as r:
                path.write_bytes(r.read())
        data = path.read_bytes()
        algo, want = f["checksum"].split(":", 1)
        got = hashlib.new(algo, data).hexdigest()
        if got != want:
            sys.exit(f"{name}: {algo} {got} != record's {want}")
        files[name] = {f"{algo}": want, "sha256": hashlib.sha256(data).hexdigest(), "size": len(data)}
    return {"record": RECORD.replace("/api/records/", "/records/"),
            "doi": meta.get("doi"), "license": meta["metadata"].get("license", {}).get("id"),
            "title": meta["metadata"].get("title"),
            "creators": [c.get("name") for c in meta["metadata"].get("creators", [])],
            "created": meta.get("created"), "files": files}


def documents(work: Path, split: str) -> list[nlm_gene.Document]:
    pmids = (work / f"Pmidlist.{split}.txt").read_text().split()
    docs = []
    with zipfile.ZipFile(work / "NLM-Gene-Corpus.zip") as z:
        names = {Path(n).name: n for n in z.namelist()}
        for pmid in pmids:
            docs.append(nlm_gene.parse_document(z.read(names[f"{pmid}.BioC.XML"])))
    return docs


def gold_genes(docs: list[nlm_gene.Document]) -> dict[str, dict | None]:
    ids = sorted({i for d in docs for m in d.mentions for i in nlm_gene.classify(m.raw_ids)[1]})
    print(f"  NodeNorm for {len(ids)} gold IDs", file=sys.stderr)
    return translator.nodenorm(ids)


def baselines(cases: list[dict], cache_path: Path) -> None:
    cache = json.loads(cache_path.read_text()) if cache_path.exists() else {}
    todo = sorted({(c["input"]["name"], c["input"]["taxon"]) for c in cases} - {
        tuple(k.split("\t")) for k in cache})
    print(f"  lookup for {len(todo)} (name, taxon) pairs ({len(cache)} cached)", file=sys.stderr)
    for n, (name, taxon) in enumerate(todo, 1):
        try:
            r = resolve.resolve_by_taxon([name], taxon)[0]
            entry = {"method": r["method"], "gene": r["gene"],
                     "claimants": r["claimants"]}
        except translator.NETWORK_ERRORS as exc:
            entry = {"error": f"{type(exc).__name__}: {exc}"[:200]}
        cache[f"{name}\t{taxon}"] = entry
        if n % 25 == 0:
            cache_path.write_text(json.dumps(cache))
            print(f"    {n}/{len(todo)}", file=sys.stderr)
    cache_path.write_text(json.dumps(cache))
    for c in cases:
        c["resolver_baseline"] = cache[f"{c['input']['name']}\t{c['input']['taxon']}"]


def write_tiers(cases: list[dict]) -> dict:
    tiers = {}
    for name, spec in TIERS.items():
        tiers[name] = {**spec, "ids": metrics.select_tier(cases, spec["caps"], spec["seed"])}
    (OUT / "tiers.json").write_text(json.dumps(tiers, indent=2) + "\n")
    return tiers


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--work", type=Path, required=True, help="download and cache directory")
    ap.add_argument("--tiers-only", action="store_true", help="recompute tiers.json from cases.jsonl")
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)

    if args.tiers_only:
        cases = [json.loads(line) for line in (OUT / "cases.jsonl").read_text().splitlines() if line]
        tiers = write_tiers(cases)
        print({t: len(v["ids"]) for t, v in tiers.items()})
        return 0

    args.work.mkdir(parents=True, exist_ok=True)
    source = download(args.work)
    docs = documents(args.work, "Test")
    genes = gold_genes(docs)
    current = sorted({g["ncbi_gene_id"] for g in genes.values() if g and g.get("ncbi_gene_id")})
    print(f"  Name Resolver synonyms for {len(current)} genes", file=sys.stderr)
    names = translator.nameres_synonyms(current)
    cases, excluded = nlm_gene.build_cases(docs, genes, names)
    baselines(cases, args.work / "baseline_cache.json")
    cases.sort(key=lambda c: c["id"])
    with (OUT / "cases.jsonl").open("w", encoding="utf-8") as fh:
        for c in cases:
            fh.write(json.dumps(c, ensure_ascii=False, sort_keys=True) + "\n")
    tiers = write_tiers(cases)
    strata = Counter(metrics.stratum(c) for c in cases)
    source.update({
        "captured": date.today().isoformat(),
        "how": "packages/gene-identity-eval/scripts/snapshot_nlm_gene.py",
        "split": "Test (Pmidlist.Test.txt); Train is left for SKILL.md iteration",
        "documents": len(docs),
        "mentions": sum(len(d.mentions) for d in docs),
        "cases": len(cases),
        "excluded": dict(sorted(excluded.items())),
        "strata": {s: strata.get(s, 0) for s in metrics.STRATA},
        "generic_rule": "single-ID mention not equal (normalised) to the gene's label or any "
                        "Name Resolver synonym: GENE or NO_SINGLE_GENE both pass",
        "generic_cases": sum(1 for c in cases if c["expected"].get("generic")),
        "tiers": {t: len(v["ids"]) for t, v in tiers.items()},
        "translator": translator.translator_versions(),
        "cases_sha256": hashlib.sha256((OUT / "cases.jsonl").read_bytes()).hexdigest(),
    })
    (OUT / "SOURCE.json").write_text(json.dumps(source, indent=2) + "\n")
    print(json.dumps({k: source[k] for k in ("cases", "excluded", "strata", "tiers")}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
