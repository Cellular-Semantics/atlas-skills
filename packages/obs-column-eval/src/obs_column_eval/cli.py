"""The `obs-column-eval` command line.

Everything prints JSON on stdout, so the eval runner can pipe it around without
parsing prose.

    obs-column-eval datasets                  # the default subset
    obs-column-eval datasets --all            # all 74
    obs-column-eval gold                      # ground truth, by field type
    obs-column-eval gold --field-type tissue  # ... one field type
    obs-column-eval notes                     # why the awkward calls went that way
    obs-column-eval candidates evals/fixtures/profiles   # what to hand-curate next
    obs-column-eval curation                  # the raw CL_KG sheets
    obs-column-eval score picks.json          # metrics, per field type
    obs-column-eval score picks.json --baseline   # ... vs the frozen n=73
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .candidates import mine
from .curation import DATA, parse_curation
from .gold import FIELD_TYPES, flatten, gold_set, notes
from .manifest import full, subset, with_ground_truth
from .score import score_by_field_type, score_picks

FROZEN_PICKS = DATA / "frozen" / "n73_picks.json"


def _load_picks(path: Path) -> dict[str, object]:
    """Normalise a picks file to ``{dsid: {field_type: [cols]}}``.

    Three shapes are accepted, because three shapes exist in the wild:

    - ``{dsid: [cols]}`` and ``{dsid: {"picks": [cols], "reasoning": ...}}`` --
      cell-type picks, the shape of every file written before field types
      existed, including the frozen n=73 baseline. Read as ``cell_type``.
    - ``{dsid: {"tissue": [...], "disease": [...]}}`` -- what the sample-field
      agent writes. A ``reasoning`` key alongside is ignored, not an error.
    """
    raw = json.loads(path.read_text())
    out: dict[str, object] = {}
    for dsid, value in raw.items():
        if isinstance(value, list):
            out[dsid] = {"cell_type": list(value)}
        elif isinstance(value, dict) and "picks" in value:
            out[dsid] = {"cell_type": list(value["picks"])}
        elif isinstance(value, dict):
            by_ft = {k: list(v) for k, v in value.items()
                     if k in FIELD_TYPES and isinstance(v, list)}
            if not by_ft:
                raise SystemExit(
                    f"{path}: {dsid} names no known field type. Expected a list of "
                    f"columns, a `picks` key, or some of {list(FIELD_TYPES)}.")
            out[dsid] = by_ft
        else:
            raise SystemExit(f"{path}: {dsid} is neither a list of columns nor an "
                             "object keyed by field type.")
    return out


def _requested(args) -> tuple[str, ...]:
    return tuple(args.field_type) if args.field_type else FIELD_TYPES


def _emit(payload) -> int:
    json.dump(payload, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="obs-column-eval",
        description="Score author-annotation-column picks against hand curation, "
                    "for cell type, tissue, developmental stage and disease.")
    ap.add_argument("--version", action="version",
                    version=f"obs-column-eval {__version__}")
    sub = ap.add_subparsers(dest="command", required=True)

    p_ds = sub.add_parser("datasets", help="The datasets to run, with ground truth.")
    p_ds.add_argument("--all", action="store_true",
                      help="All 74 datasets, not the default subset. Slow and not free.")

    p_gold = sub.add_parser("gold", help="Ground truth per dataset, by field type.")
    p_gold.add_argument("--field-type", action="append", choices=FIELD_TYPES,
                        help="Restrict to this field type. Repeatable.")

    sub.add_parser("notes", help="Per-column curation notes: why the awkward "
                                 "calls went the way they did.")

    p_cand = sub.add_parser(
        "candidates",
        help="Mine a directory of obs profiles for columns worth curating. A "
             "curation aid, by column name only -- never ground truth.")
    p_cand.add_argument("profiles_dir", type=Path)
    p_cand.add_argument("--miss", action="store_true",
                        help="Only the columns no pattern matched -- where a "
                             "field type nobody thought to name is hiding.")

    p_cur = sub.add_parser("curation", help="The gold set, per dataset.")
    p_cur.add_argument("--unfiltered", action="store_true",
                       help="Every author category, not just cell-type rows. Not "
                            "comparable to any published score.")

    p_sc = sub.add_parser("score", help="Score a picks file.")
    p_sc.add_argument("picks", type=Path)
    p_sc.add_argument("--field-type", action="append", choices=FIELD_TYPES,
                      help="Score only this field type. Repeatable; default is "
                           "every field type the picks file mentions.")
    p_sc.add_argument("--baseline", action="store_true",
                      help="Also score the frozen n=73 picks on the same datasets, so "
                           "the comparison is like for like.")

    args = ap.parse_args(argv)

    if args.command == "datasets":
        return _emit(with_ground_truth(full() if args.all else subset()))

    if args.command == "gold":
        return _emit(gold_set(_requested(args)))

    if args.command == "notes":
        return _emit(notes())

    if args.command == "candidates":
        result = mine(args.profiles_dir)
        return _emit(result["unmatched"] if args.miss else result)

    if args.command == "curation":
        return _emit(parse_curation(filter_celltype=not args.unfiltered))

    picks = _load_picks(args.picks)
    field_types = _requested(args)
    gold = gold_set(field_types)
    result = {"by_field_type": score_by_field_type(picks, gold, field_types)}

    if args.baseline:
        # Like for like: the frozen picks are cell-type only, so this compares
        # the one field type they can speak to, on the datasets they share.
        frozen = _load_picks(FROZEN_PICKS)
        ours = flatten(picks, "cell_type")
        shared = {d: frozen[d] for d in ours if d in frozen}
        curation = parse_curation()
        result["baseline"] = {
            "source": "frozen n=73 picks",
            "field_type": "cell_type",
            "n_shared_datasets": len(shared),
            "overall": (score_picks(flatten(shared, "cell_type"),
                                    curation)["overall"] if shared else None),
        }
    return _emit(result)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
