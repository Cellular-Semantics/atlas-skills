#!/usr/bin/env python3
"""Score the picker against the CL_KG gold set.

A different question from `runner.py`. That one asks whether the skill behaves
-- right tool, right flag, right reading of the result. This one asks how often
the picker is *correct*, on datasets where curators have written down the
answer.

    python3 evals/benchmark.py                  # the six default datasets
    python3 evals/benchmark.py --all            # all 74; slow, not free
    python3 evals/benchmark.py --dataset e48806af-87d1-45ae-843a-c7ee06eac672
    python3 evals/benchmark.py --profiles-only  # refresh the profile cache, no agent

Two stages, deliberately split:

1. **Profile** each dataset with the `h5ad-obs` CLI. No agent, no judgment,
   fully deterministic, and cached on disk -- so a rerun costs no bandwidth.
   This is the one place where profiling the URL is the right call: the columns
   themselves are never wanted, only the summary.
2. **Pick**, by dispatching the published `author-celltype-picker` sub-agent on
   each cached profile. This is the part under test.

Scoring uses `celltype-column-eval`, so the numbers are comparable to the frozen
n=73 baseline rather than to a fresh definition of correctness.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import pathlib
import re
import shlex
import subprocess
import sys
import time

from graders import classify_error

HERE = pathlib.Path(__file__).parent
CACHE = HERE / ".cache" / "profiles"

TAG = "v0.2.0"
GIT = "git+https://github.com/Cellular-Semantics/atlas-skills"


def _cli(env_var: str, package: str, entrypoint: str) -> list[str]:
    """The published command, unless an env var points somewhere else.

    The default is the pinned tag, so the benchmark measures what users get. The
    override exists for developing against the working tree before a tag is cut:

        H5AD_OBS_CMD="packages/h5ad-obs/.venv/bin/h5ad-obs" python3 evals/benchmark.py
    """
    override = os.environ.get(env_var)
    if override:
        return shlex.split(override)
    return ["uvx", "--from", f"{GIT}@{TAG}#subdirectory=packages/{package}", entrypoint]


H5AD_OBS = _cli("H5AD_OBS_CMD", "h5ad-obs", "h5ad-obs")
EVAL_CLI = _cli("CELLTYPE_COLUMN_EVAL_CMD", "celltype-column-eval", "celltype-column-eval")

PICK_PROMPT = (
    "Use the author-celltype-picker subagent on the obs column profile at {path}. "
    "Reply with the subagent's JSON object verbatim and nothing else."
)


def _run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


def datasets(all_: bool, only: list[str]) -> dict[str, dict]:
    out = _run([*EVAL_CLI, "datasets", *(["--all"] if all_ else [])])
    if out.returncode:
        sys.exit(f"celltype-column-eval failed:\n{out.stderr}")
    chosen = json.loads(out.stdout)
    if only:
        missing = [d for d in only if d not in chosen]
        if missing:
            sys.exit(f"not in the selected set (try --all): {', '.join(missing)}")
        chosen = {d: chosen[d] for d in only}
    return chosen


def profile(dsid: str, entry: dict, *, force: bool) -> pathlib.Path | None:
    """Cache a text profile per dataset. Returns None if obs could not be read."""
    CACHE.mkdir(parents=True, exist_ok=True)
    path = CACHE / f"{dsid}.txt"
    if path.exists() and not force:
        return path
    # Bigger obs justifies a bigger block; the 2 MB default overshoots badly on a
    # small file. See the block-size table in the remote-h5ad-obs skill.
    block = "2" if (entry.get("n_cells") or 0) > 50_000 else "0.25"
    out = _run([*H5AD_OBS, entry["url"], "--profile", "text", "--block-size", block])
    if out.returncode:
        print(f"  ! {dsid}: profile failed -- {out.stderr.strip()[:160]}")
        return None
    path.write_text(out.stdout)
    return path


def pick(dsid: str, path: pathlib.Path, timeout: int) -> dict:
    """One headless run of the published picker sub-agent."""
    cmd = ["claude", "-p", "--output-format", "json", "--max-turns", "6",
           "--allowedTools", "Task", "Read"]
    try:
        out = _run(cmd, input=PICK_PROMPT.format(path=path), timeout=timeout)
    except subprocess.TimeoutExpired:
        return {"dsid": dsid, "error": f"timed out after {timeout}s"}
    try:
        event = json.loads(out.stdout)
    except json.JSONDecodeError:
        return {"dsid": dsid, "error": f"unparseable result: {out.stdout[:200]}"}
    text = event.get("result") or ""
    row = {"dsid": dsid, "cost_usd": event.get("total_cost_usd") or 0.0, "raw": text}
    if event.get("is_error"):
        row["error"] = "agent reported an error"
        row["infra_error"] = classify_error(text)
        return row
    # The agent is told to return bare JSON; be forgiving about a fence anyway,
    # because a formatting slip is not the behaviour under test.
    match = re.search(r'\{.*"picks".*\}', text, re.DOTALL)
    if not match:
        row["error"] = "no JSON object with a `picks` key in the reply"
        return row
    try:
        payload = json.loads(match.group(0))
    except json.JSONDecodeError as e:
        row["error"] = f"picks JSON did not parse: {e}"
        return row
    row["picks"] = list(payload.get("picks", []))
    row["reasoning"] = payload.get("reasoning", "")
    return row


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--all", action="store_true", help="All 74 datasets, not the six.")
    ap.add_argument("--dataset", action="append", default=[], help="Just this one (repeatable).")
    ap.add_argument("--jobs", type=int, default=3, help="Concurrent picker runs (default 3).")
    ap.add_argument("--timeout", type=int, default=600, help="Per-dataset timeout (seconds).")
    ap.add_argument("--max-cost-usd", type=float, default=8.0,
                    help="Stop once the run has spent this much (default 8).")
    ap.add_argument("--force-profiles", action="store_true", help="Ignore the profile cache.")
    ap.add_argument("--profiles-only", action="store_true",
                    help="Refresh profiles and stop. No agent, no spend.")
    ap.add_argument("--output-dir")
    args = ap.parse_args()

    chosen = datasets(args.all, args.dataset)
    print(f"{len(chosen)} datasets")

    print("\n== profiling ==")
    profiles, unreadable = {}, []
    for dsid, entry in chosen.items():
        path = profile(dsid, entry, force=args.force_profiles)
        if path:
            profiles[dsid] = path
            print(f"  {dsid}  {entry['n_cells'] or '?':>9} cells  {path.stat().st_size:>6} B")
        else:
            unreadable.append(dsid)
    if args.profiles_only:
        print(f"\n{len(profiles)} cached under {CACHE}")
        return 0
    if not profiles:
        sys.exit("nothing to pick on")

    out_dir = pathlib.Path(args.output_dir
                           or HERE / "results" / f"benchmark-{time.strftime('%Y%m%d-%H%M%S')}")
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"\n== picking ({args.jobs} at a time) ==")
    rows, spent = [], 0.0
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.jobs) as pool:
        futures = {pool.submit(pick, d, p, args.timeout): d for d, p in profiles.items()}
        for future in concurrent.futures.as_completed(futures):
            row = future.result()
            rows.append(row)
            spent += row.get("cost_usd", 0.0)
            note = row.get("error") or ", ".join(row.get("picks", [])) or "(no picks)"
            print(f"  {row['dsid']}  ${row.get('cost_usd', 0):.2f}  {note}")
            if spent >= args.max_cost_usd:
                print(f"  ! cost ceiling ${args.max_cost_usd} reached; cancelling the rest")
                for f in futures:
                    f.cancel()
                break

    picks = {r["dsid"]: {"picks": r["picks"], "reasoning": r.get("reasoning", "")}
             for r in rows if "picks" in r}
    failed = [r for r in rows if "picks" not in r]
    (out_dir / "picks.json").write_text(json.dumps(picks, indent=2))
    (out_dir / "runs.json").write_text(json.dumps(rows, indent=2))

    if not picks:
        print("\nno usable picks; nothing to score")
        return 1

    scored = _run([*EVAL_CLI, "score", str(out_dir / "picks.json"), "--baseline"])
    if scored.returncode:
        sys.exit(f"scoring failed:\n{scored.stderr}")
    result = json.loads(scored.stdout)
    (out_dir / "scores.json").write_text(scored.stdout)

    overall = result["overall"]
    print(f"\n== n={overall['n']} ==")
    for metric in ("jaccard", "precision", "recall"):
        block = overall[metric]
        print(f"  {metric:10s} {block['mean']:.3f}  "
              f"95% CI {block['ci95'][0]:.2f}-{block['ci95'][1]:.2f}")
    hit = overall["hit_rate"]
    print(f"  hit rate   {hit['k']}/{hit['n']}")
    base = (result.get("baseline") or {}).get("overall")
    if base:
        delta = overall["jaccard"]["mean"] - base["jaccard"]["mean"]
        print(f"  frozen n=73 picker on the same datasets: "
              f"{base['jaccard']['mean']:.3f}  (delta {delta:+.3f})")

    print("\n== per dataset ==")
    for row in sorted(result["per_dataset"], key=lambda r: r["jaccard"]):
        flag = "  " if row["jaccard"] == 1.0 else "! "
        print(f"{flag}{row['dsid']}  J={row['jaccard']:.2f}")
        if row["missed_by_agent"]:
            print(f"      missed: {', '.join(row['missed_by_agent'])}")
        if row["agent_extras"]:
            print(f"      extra : {', '.join(row['agent_extras'])}")

    if unreadable:
        print(f"\nobs unreadable, not scored: {', '.join(unreadable)}")
    if failed:
        infra = [r['dsid'] for r in failed if r.get("infra_error")]
        print(f"picker produced nothing for {len(failed)}: "
              f"{', '.join(r['dsid'] for r in failed)}")
        if infra:
            print(f"  of those, the harness stopped these -- rerun: {', '.join(infra)}")
    print(f"\n${spent:.2f} spent -> {out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
