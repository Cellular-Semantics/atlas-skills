"""``gene-identity-eval``: what is in the NLM-Gene snapshot.

    gene-identity-eval info                 provenance, strata and tiers
    gene-identity-eval cases --tier l4      the tier's cases, one JSON object per line
    gene-identity-eval --version
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter

from gene_identity_eval import __version__, data, metrics


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="gene-identity-eval", description=__doc__.split("\n\n")[0])
    p.add_argument("--version", action="version", version=f"gene-identity-eval {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("info", help="provenance, strata and tiers")
    c = sub.add_parser("cases", help="print cases as JSON lines")
    c.add_argument("--tier", help="only this tier's cases (default: every case)")
    args = p.parse_args(argv)

    if args.cmd == "info":
        src = data.source()
        tiers = data.tiers()
        out = {k: src.get(k) for k in ("record", "doi", "license", "captured", "documents",
                                       "mentions", "cases", "excluded", "strata")}
        out["tiers"] = {t: dict(Counter(metrics.stratum(c) for c in data.tier_cases(t).values()))
                        for t in tiers}
        print(json.dumps(out, indent=2))
        return 0
    cases = data.tier_cases(args.tier) if args.tier else data.cases()
    for case in cases.values():
        print(json.dumps(case, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
