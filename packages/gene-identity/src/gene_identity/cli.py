"""``gene-id``: the lookup the gene-id-curation skill calls.

    gene-id resolve --taxon NCBITaxon:10090 PV SOM D1     (network: Name Resolver)
    gene-id resolve --gene-table gene_ids.tsv.gz PV SOM   (offline)
    gene-id build-table --ensembl-ids ids.txt -o gene_ids.tsv.gz
    gene-id validate x.gene-records.json                  (the skill's records: schema only)
    gene-id schema                                        (print the record schema)

``resolve`` prints a JSON list, one object per name:
``{name, method, gene: {ncbi_gene_id, label, ...} | null, claimants: [...]}``.
``label`` is the gene's official symbol.

Exit codes: 0 ok; 1 could not run (missing table or file, network down,
not JSON); 2 bad arguments, or ``validate`` found problems.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from gene_identity import __version__, records
from gene_identity.resolve import GeneIdsUnavailable, resolve_by_taxon, resolve_with_table
from gene_identity.table import build_gene_ids, read_id_list
from gene_identity.translator import NETWORK_ERRORS

_TAXON = re.compile(r"^NCBITaxon:[0-9]+$")


def _taxon(value: str) -> str:
    if not _TAXON.match(value):
        raise argparse.ArgumentTypeError(f"expected an NCBITaxon CURIE such as NCBITaxon:10090, got {value!r}")
    return value


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="gene-id", description=__doc__.split("\n\n")[0])
    p.add_argument("--version", action="version", version=f"gene-identity {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("resolve", help="claimant genes for names (JSON)")
    r.add_argument("names", nargs="+", help="names exactly as the source writes them")
    g = r.add_mutually_exclusive_group(required=True)
    g.add_argument("--taxon", type=_taxon,
                   help="NCBITaxon CURIE of a species: query Name Resolver (network)")
    g.add_argument("--gene-table", type=Path, metavar="GENE_IDS_TSV_GZ",
                   help="resolve against this gene table (offline)")

    b = sub.add_parser("build-table", help="build a gene_ids.tsv.gz from Ensembl IDs (network)")
    b.add_argument("--ensembl-ids", type=Path, required=True,
                   help="text file: one Ensembl ID per line, optionally <TAB> the dataset's symbol")
    b.add_argument("-o", "--out", type=Path, required=True)
    b.add_argument("--label", help="recorded in the table header as dataset_id")

    v = sub.add_parser("validate", help="check a .gene-records.json against the record schema")
    v.add_argument("file", type=Path)

    sub.add_parser("schema", help="print the record schema (JSON Schema 2020-12)")
    return p


def _validate(path: Path) -> int:
    try:
        data = records.load(path)
    except (OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    problems = records.validate(data)
    if problems:
        print(f"{path}: {len(problems)} problem(s)", file=sys.stderr)
        for line in problems:
            print(f"  {line}", file=sys.stderr)
        return 2
    n = len(data) if isinstance(data, list) else 0
    print(f"{path}: {n} record(s), valid")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.cmd == "validate":
        return _validate(args.file)
    if args.cmd == "schema":
        print(json.dumps(records.schema(), indent=2))
        return 0
    try:
        if args.cmd == "resolve":
            if args.gene_table:
                res = resolve_with_table(args.names, args.gene_table)
            else:
                res = resolve_by_taxon(args.names, args.taxon)
            print(json.dumps(res, indent=2))
        elif args.cmd == "build-table":
            genes = read_id_list(args.ensembl_ids)
            meta = {"dataset_id": args.label} if args.label else {}
            meta["source_file"] = args.ensembl_ids.name
            build_gene_ids(genes, args.out, meta=meta)
    except GeneIdsUnavailable as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    except NETWORK_ERRORS as exc:
        print(f"ERROR: Translator unreachable ({exc}). Nothing was looked up; "
              "do not fill in IDs from memory.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
