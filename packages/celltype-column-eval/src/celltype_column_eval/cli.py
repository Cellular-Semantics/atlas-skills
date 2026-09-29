"""The `celltype-column-eval` command line.

Everything prints JSON on stdout, so the eval runner can pipe it around without
parsing prose.

    celltype-column-eval datasets                  # the default subset
    celltype-column-eval datasets --all            # all 74
    celltype-column-eval curation                  # the gold set
    celltype-column-eval score picks.json          # metrics
    celltype-column-eval score picks.json --baseline   # ... vs the frozen n=73
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .curation import DATA, parse_curation
from .manifest import full, subset, with_ground_truth
from .score import score_picks

FROZEN_PICKS = DATA / "frozen" / "n73_picks.json"


def _load_picks(path: Path) -> dict[str, list[str]]:
    """Accept either ``{dsid: [cols]}`` or ``{dsid: {"picks": [cols], ...}}``.

    The second is what an agent writes when it also records its reasoning, and
    requiring callers to strip that first is friction for no gain.
    """
    raw = json.loads(path.read_text())
    out = {}
    for dsid, value in raw.items():
        if isinstance(value, dict):
            out[dsid] = list(value.get("picks", []))
        elif isinstance(value, list):
            out[dsid] = list(value)
        else:
            raise SystemExit(f"{path}: {dsid} is neither a list of columns nor an "
                             "object with a `picks` key.")
    return out


def _emit(payload) -> int:
    json.dump(payload, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="celltype-column-eval",
        description="Score author-cell-type-column picks against CL_KG curation.")
    ap.add_argument("--version", action="version",
                    version=f"celltype-column-eval {__version__}")
    sub = ap.add_subparsers(dest="command", required=True)

    p_ds = sub.add_parser("datasets", help="The datasets to run, with ground truth.")
    p_ds.add_argument("--all", action="store_true",
                      help="All 74 datasets, not the default subset. Slow and not free.")

    p_cur = sub.add_parser("curation", help="The gold set, per dataset.")
    p_cur.add_argument("--unfiltered", action="store_true",
                       help="Every author category, not just cell-type rows. Not "
                            "comparable to any published score.")

    p_sc = sub.add_parser("score", help="Score a picks file.")
    p_sc.add_argument("picks", type=Path)
    p_sc.add_argument("--baseline", action="store_true",
                      help="Also score the frozen n=73 picks on the same datasets, so "
                           "the comparison is like for like.")

    args = ap.parse_args(argv)

    if args.command == "datasets":
        return _emit(with_ground_truth(full() if args.all else subset()))

    if args.command == "curation":
        return _emit(parse_curation(filter_celltype=not args.unfiltered))

    picks = _load_picks(args.picks)
    curation = parse_curation()
    result = score_picks(picks, curation)
    if args.baseline:
        frozen = _load_picks(FROZEN_PICKS)
        shared = {d: frozen[d] for d in picks if d in frozen}
        result["baseline"] = {
            "source": "frozen n=73 picks",
            "n_shared_datasets": len(shared),
            "overall": score_picks(shared, curation)["overall"] if shared else None,
        }
    return _emit(result)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
