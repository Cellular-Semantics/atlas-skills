"""The eval run log: one committed JSON file per run, and an index generated
from them.

    evals/runs/<date>-<scope>-<commit>.json   one run, never edited afterwards
    evals/runs/README.md                     the index, regenerated on every write

Why committed files and not a tracker: a run sits next to the code and gold
version it measured, shows up in review, and needs no account. The raw run
directory (`evals/results/`, gitignored) keeps the full transcripts; a run
file keeps what is needed to compare runs months later.

Pure functions plus two writers; `benchmark.py` calls `write_run`.
"""
from __future__ import annotations

import json
import pathlib

RUNS = pathlib.Path(__file__).parent / "runs"
INDEX = RUNS / "README.md"

#: Bump when the shape of a run file changes, so old files stay readable.
SCHEMA = 1

#: Keys every run file has. `test_run_log.py` holds the committed files to it.
REQUIRED_RUN_KEYS = {"date", "scope", "command", "note", "n_requested", "n_scored",
                     "unreadable", "no_picks_returned", "cost_usd", "picker",
                     "gold_snapshot", "profiles"}


def _compact(row: dict, tier: str | None) -> dict:
    """The per-dataset facts worth keeping across runs."""
    return {
        "dsid": row["dsid"],
        "tier": tier,
        "jaccard": round(row["jaccard"], 4),
        "picks": row["picks"],
        "missed": row["missed_by_agent"],
        "extra": row["agent_extras"],
    }


def build_record(*, run: dict, cell_type: dict, baselines: dict,
                 manifest: dict) -> dict:
    """A run file's content.

    ``run`` is the run's metadata (see REQUIRED_RUN_KEYS). ``cell_type`` is
    the ``by_field_type.cell_type`` block from ``obs-column-eval score``;
    ``baselines`` its ``baseline`` block; ``manifest`` the test set, for
    tagging each dataset with its tier.
    """
    missing = REQUIRED_RUN_KEYS - set(run)
    if missing:
        raise ValueError(f"run metadata lacks {sorted(missing)}")
    by_tier = cell_type.get("by_tier", {})
    tiers = {}
    for tier, block in by_tier.get("tiers", {}).items():
        entry = {"overall": block}
        base = (baselines.get(tier) or {})
        if base.get("overall"):
            entry["baseline"] = {
                "source": base["source"],
                "n": base["overall"]["n"],
                "jaccard": base["overall"]["jaccard"]["mean"],
                "delta_jaccard": block["jaccard"]["mean"] - base["overall"]["jaccard"]["mean"],
            }
        tiers[tier] = entry
    record = {
        "schema": SCHEMA,
        "run": run,
        "tiers": tiers,
        "all": by_tier.get("all") if len(tiers) > 1 else None,
        "by_group": by_tier.get("by_group", {}),
        "per_dataset": [_compact(r, (manifest.get(r["dsid"]) or {}).get("tier"))
                        for r in sorted(cell_type.get("per_dataset", []),
                                        key=lambda r: r["dsid"])],
    }
    if {"n73", "l4"} <= set(tiers):
        record["gap_n73_minus_l4"] = (tiers["n73"]["overall"]["jaccard"]["mean"]
                                      - tiers["l4"]["overall"]["jaccard"]["mean"])
    return record


def run_filename(run: dict, runs_dir: pathlib.Path = RUNS) -> pathlib.Path:
    """``<date>-<scope>-<commit>.json``; a second run on the same day and
    commit gets ``-2``, and so on. Never overwrites."""
    stem = f"{run['date']}-{run['scope']}-{run['picker'].get('commit') or 'nocommit'}"
    path = runs_dir / f"{stem}.json"
    n = 2
    while path.exists():
        path = runs_dir / f"{stem}-{n}.json"
        n += 1
    return path


def write_run(record: dict, runs_dir: pathlib.Path = RUNS) -> pathlib.Path:
    runs_dir.mkdir(parents=True, exist_ok=True)
    path = run_filename(record["run"], runs_dir)
    path.write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n")
    write_index(runs_dir)
    return path


def _fmt_tier(record: dict, tier: str) -> str:
    entry = record["tiers"].get(tier)
    if not entry:
        return ""
    text = f"{entry['overall']['jaccard']['mean']:.3f} (n={entry['overall']['n']})"
    base = entry.get("baseline")
    if base:
        text += f" Δ{base['delta_jaccard']:+.3f}"
    return text


def _fmt_cost(cost: float | None) -> str:
    return "not recorded" if cost is None else f"${cost:.2f}"


def render_index(runs_dir: pathlib.Path = RUNS) -> str:
    rows = []
    for path in sorted(runs_dir.glob("*.json"), reverse=True):
        record = json.loads(path.read_text())
        run = record["run"]
        picker = run["picker"]
        models = ", ".join(picker.get("models_used") or []) or "not recorded"
        rows.append(
            f"| {run['date']} | {run['scope']} | {_fmt_tier(record, 'n73')} | "
            f"{_fmt_tier(record, 'l4')} | {_fmt_cost(run['cost_usd'])} | "
            f"{picker.get('plugin', '?')} @ {picker.get('commit', '?')} | {models} | "
            f"{run['note']} | [{path.name}]({path.name}) |")
    return "\n".join([
        "# Benchmark run log",
        "",
        "One file per run of `evals/benchmark.py`, newest first. Generated by",
        "`evals/run_log.py` on every run that writes a file. Edit the run files' `note`",
        "only by hand, and regenerate this with `python3 evals/run_log.py`.",
        "",
        "Jaccard is cell type, per tier; Δ is against that tier's frozen baseline on",
        "the same datasets. Full transcripts stay in the gitignored `evals/results/`.",
        "",
        "| date | scope | n73 Jaccard | l4 Jaccard | cost | picker | models | note | file |",
        "|---|---|---|---|---|---|---|---|---|",
        *rows,
        "",
    ])


def write_index(runs_dir: pathlib.Path = RUNS) -> None:
    (runs_dir / "README.md").write_text(render_index(runs_dir))


if __name__ == "__main__":
    write_index()
    print(f"regenerated {INDEX}")
