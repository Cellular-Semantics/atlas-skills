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

#: Profiles are COMMITTED, not cached. They are the deterministic output of a
#: pinned CLI, 570 KB for the whole test set, and re-fetching them means ~1.5 GB
#: of range reads and the better part of an hour -- which made re-scoring the
#: picker something you thought twice about. Committed, the accuracy arm needs
#: no network at all, and anyone can reproduce a published number.
#:
#: A second benefit: the scored inputs stop moving. CELLxGENE re-ingests and
#: re-annotates, so a live profile makes the benchmark assert third-party
#: content that can change underneath it. A frozen one does not.
PROFILES = HERE / "fixtures" / "profiles"
PROVENANCE = PROFILES / "PROVENANCE.json"

#: Picks are the thing under test, so they are NOT committed -- but they are
#: cached locally, so an interrupted run costs only what is outstanding.
PICKS_CACHE = HERE / ".cache" / "picks"

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
    "Do not read the profile yourself -- the subagent reads it, and a fresh context "
    "per dataset is the point. Reply with the subagent's JSON object verbatim and "
    "nothing else."
)

#: Turn budget for the dispatching wrapper, not the picker. Measured: a clean
#: dispatch takes 5, so the original 6 killed any run that paused to think and
#: charged for the truncated attempt. 30% of a full run died that way.
DEFAULT_MAX_TURNS = 14


def _run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


def check_profile_provenance() -> None:
    """Warn when the installed reader no longer matches the committed profiles.

    The profile format is what the picker sees. If it changes -- new fields,
    different sampling, changed constant detection -- a score against stale
    fixtures measures the old inputs while claiming to measure the new ones.
    """
    if not PROVENANCE.exists():
        return
    recorded = json.loads(PROVENANCE.read_text()).get("captured_by", "")
    out = _run([*H5AD_OBS, "--version"])
    installed = out.stdout.strip() or out.stderr.strip()
    if installed and recorded and installed != recorded:
        print(f"  ! profiles were captured by {recorded}, but {installed} is installed.")
        print("    If the profile format changed, regenerate before trusting a score:")
        print("      python3 evals/benchmark.py --all --profiles-only --force-profiles")


def _extract_picks(text: str) -> dict | None:
    """Pull the picks object out of a reply that may carry extra text.

    The agent is told to return bare JSON, and a formatting slip is not the
    behaviour under test, so be forgiving: decode the first well-formed object
    with a `picks` key and ignore whatever surrounds it.

    Done with raw_decode rather than a regex. A greedy brace-to-brace pattern spans
    from the first brace to the last one in the whole reply, so a trailing line
    -- even a closing fence -- swallows it and the parse fails. That cost two
    datasets on the first full run.
    """
    decoder = json.JSONDecoder()
    for start, char in enumerate(text):
        if char != "{":
            continue
        try:
            obj, _end = decoder.raw_decode(text, start)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict) and "picks" in obj:
            return obj
    return None


def _picker_provenance() -> dict:
    """What produced these picks, so a recorded number can be traced back.

    A score with no record of which agent definition made it is not a
    measurement of anything.
    """
    out = {}
    listing = _run(["claude", "plugin", "list"]).stdout
    match = re.search(r"author-celltype-columns@\S+\s+Version:\s*(\S+)\s+Scope:\s*(\S+)",
                      listing, re.DOTALL)
    if match:
        out["plugin"] = (f"author-celltype-columns {match.group(1)} "
                         f"({match.group(2)} scope)")
    sha = _run(["git", "rev-parse", "--short", "HEAD"], cwd=HERE).stdout.strip()
    if sha:
        out["commit"] = sha
    agent = HERE.parent / "plugins/author-celltype-columns/agents/author-celltype-picker.md"
    if agent.exists():
        import hashlib
        out["agent_sha256"] = hashlib.sha256(agent.read_bytes()).hexdigest()[:12]
    return out


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
    """The committed profile, re-fetching only with --force-profiles.

    Returns None if obs could not be read.
    """
    PROFILES.mkdir(parents=True, exist_ok=True)
    path = PROFILES / f"{dsid}.txt"
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


def pick(dsid: str, path: pathlib.Path, timeout: int, *, force: bool = False,
         max_turns: int = DEFAULT_MAX_TURNS) -> dict:
    """One headless run of the picker sub-agent, cached on disk.

    A full run costs real money and takes an hour. Caching each pick means a
    spend ceiling, a rate limit or a Ctrl-C costs only the datasets still
    outstanding, not the whole run again.
    """
    PICKS_CACHE.mkdir(parents=True, exist_ok=True)
    cached = PICKS_CACHE / f"{dsid}.json"
    if cached.exists() and not force:
        row = json.loads(cached.read_text())
        row["cached"] = True
        row["cost_usd"] = 0.0  # already paid for; do not count it twice
        return row
    cmd = ["claude", "-p", "--output-format", "json", "--max-turns", str(max_turns),
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
    row = {"dsid": dsid, "cost_usd": event.get("total_cost_usd") or 0.0, "raw": text,
           "subtype": event.get("subtype"), "turns": event.get("num_turns")}
    if event.get("is_error"):
        # Name the failure. "agent reported an error" covers a rate limit, a
        # turn-budget overrun and a genuine refusal, which need different
        # responses -- raise --jobs down, raise --max-turns, or look at the case.
        row["error"] = f"agent error ({event.get('subtype') or 'unknown'}, "
        row["error"] += f"{event.get('num_turns')} turns)"
        row["infra_error"] = classify_error(text)
        return row
    payload = _extract_picks(text)
    if payload is None:
        row["error"] = "no JSON object with a `picks` key in the reply"
        return row
    row["picks"] = list(payload.get("picks", []))
    row["reasoning"] = payload.get("reasoning", "")
    cached.write_text(json.dumps(row, indent=2))  # only successes are cached
    return row


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--all", action="store_true", help="All 74 datasets, not the six.")
    ap.add_argument("--dataset", action="append", default=[], help="Just this one (repeatable).")
    ap.add_argument("--jobs", type=int, default=3, help="Concurrent picker runs (default 3).")
    ap.add_argument("--profile-jobs", type=int, default=4,
                    help="Concurrent profile reads (default 4). Bandwidth-bound, not "
                         "rate-limited, so this can be higher than --jobs.")
    ap.add_argument("--timeout", type=int, default=600, help="Per-dataset timeout (seconds).")
    ap.add_argument("--max-turns", type=int, default=DEFAULT_MAX_TURNS,
                    help=f"Turn budget for the dispatching wrapper (default "
                         f"{DEFAULT_MAX_TURNS}). Too low and runs die mid-dispatch and "
                         "are charged for.")
    ap.add_argument("--max-cost-usd", type=float, default=8.0,
                    help="Stop once the run has spent this much (default 8).")
    ap.add_argument("--force-profiles", action="store_true",
                    help="Re-fetch every profile and overwrite the committed fixtures. "
                         "Needed only when the profile format changes; costs ~1.5 GB.")
    ap.add_argument("--force-picks", action="store_true", help="Ignore the picks cache.")
    ap.add_argument("--profiles-only", action="store_true",
                    help="Refresh profiles and stop. No agent, no spend.")
    ap.add_argument("--output-dir")
    ap.add_argument("--record", metavar="PATH",
                    help="Also write a committed summary here, e.g. "
                         "docs/benchmark-results.json. Timestamped run directories are "
                         "gitignored; this is the one that goes in a PR, so a change to "
                         "the picker shows up as a diff in review rather than a claim.")
    args = ap.parse_args()

    chosen = datasets(args.all, args.dataset)
    print(f"{len(chosen)} datasets")

    print(f"\n== profiles ({args.profile_jobs} at a time if fetching) ==")
    check_profile_provenance()
    profiles, unreadable = {}, []
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.profile_jobs) as pool:
        jobs = {pool.submit(profile, d, e, force=args.force_profiles): d
                for d, e in chosen.items()}
        for future in concurrent.futures.as_completed(jobs):
            dsid = jobs[future]
            path = future.result()
            if path:
                profiles[dsid] = path
                cells = chosen[dsid]["n_cells"] or "?"
                print(f"  {dsid}  {cells:>9} cells  {path.stat().st_size:>6} B")
            else:
                unreadable.append(dsid)
    if args.profiles_only:
        print(f"\n{len(profiles)} profiles under {PROFILES}")
        if args.force_profiles:
            print("Regenerated. Commit them, and re-score: the picker's inputs changed.")
        return 0
    if not profiles:
        sys.exit("nothing to pick on")

    out_dir = pathlib.Path(args.output_dir
                           or HERE / "results" / f"benchmark-{time.strftime('%Y%m%d-%H%M%S')}")
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"\n== picking ({args.jobs} at a time) ==")
    rows, spent = [], 0.0
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.jobs) as pool:
        futures = {pool.submit(pick, d, p, args.timeout, force=args.force_picks,
                               max_turns=args.max_turns): d
                   for d, p in profiles.items()}
        for future in concurrent.futures.as_completed(futures):
            row = future.result()
            rows.append(row)
            spent += row.get("cost_usd", 0.0)
            note = row.get("error") or ", ".join(row.get("picks", [])) or "(no picks)"
            tag = "cached" if row.get("cached") else f"${row.get('cost_usd', 0):.2f}"
            print(f"  {row['dsid']}  {tag:>7}  {note}")
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

    if args.record:
        record = pathlib.Path(args.record)
        record.parent.mkdir(parents=True, exist_ok=True)
        record.write_text(json.dumps({
            "run": {
                "date": time.strftime("%Y-%m-%d"),
                "datasets": "all" if args.all else "subset",
                "n_scored": overall["n"],
                "n_requested": len(chosen),
                "unreadable": sorted(unreadable),
                "no_picks_returned": sorted(r["dsid"] for r in failed),
                "picker": _picker_provenance(),
            },
            "overall": overall,
            "baseline": result.get("baseline"),
            "per_dataset": result["per_dataset"],
        }, indent=2) + "\n")
        print(f"\nrecorded -> {record}")

    if unreadable:
        print(f"\nobs unreadable, not scored: {', '.join(unreadable)}")
    if failed:
        print(f"\npicker produced nothing for {len(failed)}:")
        for row in failed:
            print(f"  {row['dsid']}  {row.get('error')}")
        infra = [r["dsid"] for r in failed if r.get("infra_error")]
        if infra:
            print(f"  the harness stopped these -- rerun: {', '.join(infra)}")
        print("  Failures are not cached, so re-running picks up only these.")
    print(f"\n${spent:.2f} spent -> {out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
