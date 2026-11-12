"""How much of what a picker can get wrong does the picks.json check catch?

The thing under test is ``obs-column-eval check-picks``, the logic behind the
author-annotation-columns hook. Its inputs are real: the 73 frozen cell-type
picker answers, each checked against the obs profile of the dataset it was
picked from. Its *errors* are synthetic. Each mutation class below is one
specific way a report goes wrong, applied the same way to every dataset it can
be applied to. So the rates below measure the checker against these mutations.
They do not measure how often a real picker makes each mistake.

One class is there to show the check's limit, not its reach.
``wrong_but_real`` adds a column that exists and is not a portal field: a wrong
pick that only judgement can catch. The check is not meant to catch it, and the
expected rate is 0. That kind of error is what the evals measure, and the two
should not be confused.

    python3 evals/picks_catch_rate.py            # the table, as markdown
    python3 evals/picks_catch_rate.py --json     # ... as JSON

Deterministic, offline, free. Needs ``obs-column-eval[check]`` installed.
"""
from __future__ import annotations

import argparse
import copy
import json
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path

from obs_column_eval.candidates import column_names
from obs_column_eval.check import check_report
from obs_column_eval.cli import FROZEN_PICKS

PROFILES = Path(__file__).parent / "fixtures" / "profiles"
PORTAL = {"cell_type", "tissue", "development_stage", "disease"}

#: Rejected unmutated, and rightly: the picker took BICCN_ontology_term_id. See
#: packages/obs-column-eval/tests/test_schema.py. Left out of the mutation base
#: so that a mutation is never "caught" by a fault already present.
KNOWN_BAD = {"e48806af-87d1-45ae-843a-c7ee06eac672"}

Report = dict
Mutation = Callable[[Report, list[str], str], Report | None]


def base_report(answer: dict, profile: Path) -> Report:
    return {
        "schema_version": 1,
        "source": str(profile),
        "requested": ["cell_type"],
        "picks": {"cell_type": list(answer["picks"])},
        "reasoning": {"author-celltype-picker": answer["reasoning"]},
    }


def _add(report: Report, column: str) -> Report:
    out = copy.deepcopy(report)
    out["picks"]["cell_type"].append(column)
    return out


def _replace_first(report: Report, columns: list[str], change) -> Report | None:
    picks = report["picks"]["cell_type"]
    if not picks:
        return None
    new = change(picks[0])
    if new is None or new == picks[0] or new in columns:
        return None
    out = copy.deepcopy(report)
    out["picks"]["cell_type"][0] = new
    return out


def invented(report, columns, _other):
    """A plausible finer level that the dataset does not have."""
    base = report["picks"]["cell_type"][0] if report["picks"]["cell_type"] else "celltype"
    name = f"{base}_fine"
    return None if name in columns else _add(report, name)


def recased(report, columns, _other):
    """The right column with a different first letter case: `Cell_type` for `cell_type`."""
    return _replace_first(report, columns, lambda c: c[0].swapcase() + c[1:])


def separator(report, columns, _other):
    """`.` and `_` swapped: `celltype_l2` for `celltype.l2`."""
    def swap(c):
        if "." in c:
            return c.replace(".", "_")
        if "_" in c:
            return c.replace("_", ".")
        return None
    return _replace_first(report, columns, swap)


def borrowed(report, columns, other):
    """A real column from a different dataset, remembered rather than read."""
    return None if other in columns else _add(report, other)


def portal(report, _columns, _other):
    """The portal's own field, which is in obs and is never a pick."""
    return _add(report, "cell_type")


def portal_term_id(report, _columns, _other):
    return _add(report, "cell_type_ontology_term_id")


def wrong_field_key(report, _columns, _other):
    out = copy.deepcopy(report)
    out["picks"] = {"celltype": out["picks"].pop("cell_type")}
    return out


def dropped_field_type(report, _columns, _other):
    """Tissue asked for and silently left out."""
    out = copy.deepcopy(report)
    out["requested"] = ["cell_type", "tissue"]
    out["reasoning"]["author-sample-field-picker"] = "single-tissue atlas"
    return out


def missing_reasoning(report, _columns, _other):
    out = copy.deepcopy(report)
    out["reasoning"] = {}
    return out


def wrong_but_real(report, columns, _other):
    """A real, non-portal column that was not picked. Not catchable by design."""
    for c in columns:
        if (c not in report["picks"]["cell_type"] and c not in PORTAL
                and not c.endswith("_ontology_term_id")):
            return _add(report, c)
    return None


MUTATIONS: dict[str, Mutation] = {
    "invented": invented,
    "recased": recased,
    "separator": separator,
    "borrowed": borrowed,
    "portal": portal,
    "portal_term_id": portal_term_id,
    "wrong_field_key": wrong_field_key,
    "dropped_field_type": dropped_field_type,
    "missing_reasoning": missing_reasoning,
    "wrong_but_real": wrong_but_real,
}

#: The one class the check is not meant to catch.
NOT_CATCHABLE = {"wrong_but_real"}


def _check(report: Report, workdir: Path) -> bool:
    """True if the checker rejects the report."""
    path = workdir / "picks.json"
    path.write_text(json.dumps(report))
    return not check_report(path)["ok"]


def measure() -> dict:
    frozen = json.loads(FROZEN_PICKS.read_text())
    dsids = sorted(frozen)
    columns = {d: column_names((PROFILES / f"{d}.txt").read_text()) for d in dsids}

    result: dict = {"unmutated": {}, "mutations": {}}
    with tempfile.TemporaryDirectory() as tmp:
        workdir = Path(tmp)

        rejected = [d for d in dsids
                    if _check(base_report(frozen[d], PROFILES / f"{d}.txt"), workdir)]
        result["unmutated"] = {
            "n": len(dsids),
            "rejected": rejected,
            "false_rejects": sorted(set(rejected) - KNOWN_BAD),
            "known_bad_caught": sorted(KNOWN_BAD & set(rejected)),
        }

        clean = [d for d in dsids if d not in KNOWN_BAD]
        for name, mutate in MUTATIONS.items():
            applied = caught = 0
            for i, d in enumerate(clean):
                # A column from the next dataset along: deterministic, and real.
                donor = columns[clean[(i + 1) % len(clean)]]
                other = next((c for c in donor if c not in columns[d]
                              and c not in PORTAL), None)
                report = base_report(frozen[d], PROFILES / f"{d}.txt")
                mutated = mutate(report, columns[d], other) if other else None
                if mutated is None:
                    continue
                applied += 1
                caught += _check(mutated, workdir)
            result["mutations"][name] = {
                "applied": applied,
                "caught": caught,
                "rate": round(caught / applied, 3) if applied else None,
                "catchable": name not in NOT_CATCHABLE,
                "what": (mutate.__doc__ or "").strip().splitlines()[0]
                        if mutate.__doc__ else name.replace("_", " "),
            }
    return result


def markdown(result: dict) -> str:
    u = result["unmutated"]
    lines = [
        f"Unmutated: {u['n'] - len(u['rejected'])}/{u['n']} frozen answers pass; "
        f"{len(u['false_rejects'])} false rejects; "
        f"{len(u['known_bad_caught'])} known picker error caught.",
        "",
        "| mutation | applied | caught | rate | meant to catch |",
        "|---|---|---|---|---|",
    ]
    for name, m in result["mutations"].items():
        rate = "—" if m["rate"] is None else f"{m['rate']:.0%}"
        lines.append(f"| `{name}` | {m['applied']} | {m['caught']} | {rate} | "
                     f"{'yes' if m['catchable'] else 'no'} |")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    result = measure()
    sys.stdout.write(json.dumps(result, indent=2) + "\n" if args.json else markdown(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
