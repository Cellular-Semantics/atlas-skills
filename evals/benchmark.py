#!/usr/bin/env python3
"""Score the picker against the CL_KG gold set.

A different question from `runner.py`. That one asks whether the skill behaves
-- right tool, right flag, right reading of the result. This one asks how often
the picker is *correct*, on datasets where curators have written down the
answer.

    python3 evals/benchmark.py                  # the six default datasets
    python3 evals/benchmark.py --all            # all 187 (n73 + l4); slow, not free
    python3 evals/benchmark.py --tier l4        # one tier
    python3 evals/benchmark.py --tier l4 --freeze   # ... and make it l4's frozen baseline
    python3 evals/benchmark.py --dataset e48806af-87d1-45ae-843a-c7ee06eac672
    python3 evals/benchmark.py --profiles-only  # refresh the profile cache, no agent

Two stages, deliberately split:

1. **Profile** each dataset with the `h5ad-obs` CLI. No agent, no judgment,
   fully deterministic, and cached on disk -- so a rerun costs no bandwidth.
   This is the one place where profiling the URL is the right call: the columns
   themselves are never wanted, only the summary.
2. **Pick**, by dispatching the published `author-celltype-picker` sub-agent on
   each cached profile. This is the part under test.

Scoring uses `obs-column-eval`, so the numbers are comparable to the frozen
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

from run_log import build_record, write_run

from graders import classify_error

HERE = pathlib.Path(__file__).parent
#: Where --freeze writes a tier's baseline: the working tree's obs-column-eval,
#: so the new baseline ships with the package's next release.
EVAL_SRC = HERE.parent / "packages" / "obs-column-eval" / "src"

#: Profiles are COMMITTED, not cached. They are the deterministic output of a
#: pinned CLI, ~1.4 MB for the whole test set, and re-fetching them means several GB
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

#: The published packages, pinned the way the skills pin them: GitHub source
#: archives of each package's own release tag. One pin per package -- they
#: release separately. scripts/versions.py collects these alongside the skills'
#: pins, so CI installs them on every pull request and nightly; this line used to
#: name a tag (v0.3.0) that was never pushed, and nothing noticed. Move them when
#: a package releases.
#: Each pin is one string literal on one line, so versions.py can find it.
H5AD_OBS_PIN = "https://github.com/Cellular-Semantics/atlas-skills/archive/refs/tags/pkg-h5ad-obs--v0.3.2.tar.gz#subdirectory=packages/h5ad-obs"
OBS_COLUMN_EVAL_PIN = "https://github.com/Cellular-Semantics/atlas-skills/archive/refs/tags/pkg-obs-column-eval--v0.5.0.tar.gz#subdirectory=packages/obs-column-eval"


def _cli(env_var: str, pin: str, entrypoint: str) -> list[str]:
    """The published command, unless an env var points somewhere else.

    The default is the pinned release, so the benchmark measures what users get.
    The override exists for developing against the working tree before a tag is
    cut:

        H5AD_OBS_CMD="packages/h5ad-obs/.venv/bin/h5ad-obs" python3 evals/benchmark.py
    """
    override = os.environ.get(env_var)
    if override:
        return shlex.split(override)
    return ["uvx", "--from", pin, entrypoint]


H5AD_OBS = _cli("H5AD_OBS_CMD", H5AD_OBS_PIN, "h5ad-obs")
EVAL_CLI = _cli("OBS_COLUMN_EVAL_CMD", OBS_COLUMN_EVAL_PIN, "obs-column-eval")

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
    # Every install of the plugin, with its status. The one that ran is an
    # enabled one, local scope first (that is what a working-tree run uses);
    # taking the first listed would name a disabled install from another
    # marketplace.
    installs = re.findall(
        r"author-annotation-columns@(\S+)\s+Version:\s*(\S+)(?:\s+Read from:[^\n]*)?"
        r"\s+Scope:\s*(\S+)\s+Status:\s*\S+\s*(\w+)", listing)
    enabled = [i for i in installs if i[3] == "enabled"]
    enabled.sort(key=lambda i: i[2] != "local")
    if enabled:
        source, version, scope, _ = enabled[0]
        out["plugin"] = f"author-annotation-columns {version} ({scope} scope, {source})"
    else:
        out["plugin"] = "author-annotation-columns: no enabled install found"
    sha = _run(["git", "rev-parse", "--short", "HEAD"], cwd=HERE).stdout.strip()
    if sha:
        out["commit"] = sha
        # Uncommitted changes to what is measured make the commit a lie.
        dirty = _run(["git", "status", "--porcelain", "--", "plugins/author-annotation-columns",
                      "packages/obs-column-eval"], cwd=HERE.parent).stdout.strip()
        if dirty:
            out["uncommitted_changes"] = True
    agent = HERE.parent / "plugins/author-annotation-columns/agents/author-celltype-picker.md"
    if agent.exists():
        import hashlib
        out["agent_sha256"] = hashlib.sha256(agent.read_bytes()).hexdigest()[:12]
        declared = re.search(r"^model:\s*(\S+)", agent.read_text(), re.MULTILINE)
        if declared:
            out["declared_model"] = declared.group(1)
    claude = _run(["claude", "--version"]).stdout.strip()
    if claude:
        out["claude_code"] = claude
    return out


def datasets(all_: bool, only: list[str], tier: str | None = None) -> dict[str, dict]:
    flags = ["--tier", tier] if tier else (["--all"] if all_ else [])
    out = _run([*EVAL_CLI, "datasets", *flags])
    if out.returncode:
        sys.exit(f"obs-column-eval failed:\n{out.stderr}")
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


def write_provenance(profiles: dict, unreadable: list[str]) -> None:
    """Record what produced the committed profiles, right after producing them.

    This used to be maintained by hand, which meant a regeneration left it
    describing the previous reader while the .txt files described the new one --
    and the staleness check reads exactly this file. Anything that must be kept
    in sync with a generated artefact should be generated with it.

    Human-written `missing` reasons are carried forward for datasets that are
    still missing; a newly failing one gets a placeholder worth replacing.
    """
    import hashlib

    old = json.loads(PROVENANCE.read_text()) if PROVENANCE.exists() else {}
    old_missing = old.get("missing", {})
    old_profiles = old.get("profiles", {})
    today = time.strftime("%Y-%m-%d")

    version = _run([*H5AD_OBS, "--version"])
    captured_by = (version.stdout.strip() or version.stderr.strip()) or "unknown"
    commit = _run(["git", "rev-parse", "--short", "HEAD"]).stdout.strip() or "unknown"

    entries, total = {}, 0
    for dsid, path in sorted(profiles.items()):
        text = path.read_text()
        header = text.splitlines()[1]        # "<n> rows x <m> columns; <k> rows scanned..."
        n_rows, n_cols = int(header.split()[0]), int(header.split()[3])
        n_scanned = int(header.split("; ")[1].split()[0])
        size = path.stat().st_size
        total += size
        sha = hashlib.sha256(text.encode()).hexdigest()[:16]
        prior = old_profiles.get(dsid, {})
        entries[dsid] = {
            "n_rows": n_rows, "n_columns": n_cols, "n_scanned": n_scanned,
            "bytes": size,
            "sha256": sha,
            # When this file was captured. An unchanged file keeps its date (or
            # the run-wide date it had before per-file dates were recorded).
            "captured": (prior.get("captured") or old.get("captured") or today)
                        if prior.get("sha256") == sha else today,
        }

    PROVENANCE.write_text(json.dumps({
        "what": old.get("what", "Text obs column profiles for the benchmark test "
                        "set, captured once and committed so re-scoring the picker "
                        "needs no network. Regenerate with `python3 evals/benchmark.py "
                        "--all --profiles-only --force-profiles`."),
        "captured": today,
        "captured_by": captured_by,
        "commit": commit,
        "n_datasets": len(entries),
        "total_bytes": total,
        "note": old.get("note", "The profile FORMAT is coupled to the h5ad-obs "
                        "version above. If that changes what the picker sees -- new "
                        "fields, different sampling, changed constant detection -- "
                        "these must be regenerated and the benchmark re-scored. "
                        "benchmark.py warns when the installed version differs."),
        "missing": {d: old_missing.get(d, "profile failed at capture time; reason "
                                          "not recorded -- rerun and replace this.")
                    for d in sorted(unreadable)},
        "profiles": entries,
    }, indent=2) + "\n")


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
           "subtype": event.get("subtype"), "turns": event.get("num_turns"),
           # Exact model ids, the dispatching wrapper's and the picker's: the
           # agent declares an alias (`model: sonnet`), which moves over time.
           "models": sorted(event.get("modelUsage") or {})}
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


def _report(title: str, block: dict) -> None:
    print(f"\n== {title} ==")
    for metric in ("jaccard", "precision", "recall"):
        m = block[metric]
        print(f"  {metric:10s} {m['mean']:.3f}  95% CI {m['ci95'][0]:.2f}-{m['ci95'][1]:.2f}")
    hit = block["hit_rate"]
    print(f"  hit rate   {hit['k']}/{hit['n']}")


def freeze_baseline(tier: str, picks: dict, result: dict, run_info: dict,
                    chosen: dict) -> None:
    """Write a run as a tier's frozen baseline, beside n73's in obs-column-eval.

    Refuses a partial run: a baseline that silently covers part of a tier would
    be compared against full runs later, and every delta would be wrong.
    """
    readable = set(chosen) - set(run_info["unreadable"])
    missing = sorted(readable - set(picks))
    if missing:
        sys.exit(f"not freezing: no picks for {len(missing)} readable {tier} "
                 f"datasets ({', '.join(missing[:5])}...). Re-run to fill them.")
    frozen_dir = EVAL_SRC / "obs_column_eval" / "data" / "frozen"
    (frozen_dir / f"{tier}_picks.json").write_text(
        json.dumps(dict(sorted(picks.items())), indent=2) + "\n")
    tier_block = result["by_tier"]["tiers"][tier]
    (frozen_dir / f"{tier}_scores.json").write_text(json.dumps({
        "overall": tier_block,
        "_provenance": {
            "note": f"The first picker scored on {tier}, frozen as its baseline. "
                    "Later runs on this tier report their delta against it.",
            "picker": run_info["picker"],
            "date": run_info["date"],
            "gold_snapshot": json.loads(
                (frozen_dir.parent / "curation" / "SOURCE.json").read_text())["commit"],
        },
    }, indent=2) + "\n")
    print(f"\nfrozen as the {tier} baseline -> {frozen_dir}/{tier}_*.json")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--all", action="store_true", help="The whole test set (n73 + l4), not the six.")
    ap.add_argument("--tier", choices=("n73", "l4"),
                    help="One tier of the test set instead of the six: n73 (frozen, "
                         "published) or l4 (added from the 2026-11 snapshot).")
    ap.add_argument("--freeze", action="store_true",
                    help="With --tier l4: write this run's picks and scores as l4's "
                         "frozen baseline in obs-column-eval. Only for a run that "
                         "covered the whole tier. n73's baseline is never rewritten.")
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
    ap.add_argument("--log", action="store_true",
                    help="Write this run to the run log (evals/runs/). Automatic for "
                         "--all and --tier; use it to log a subset or --dataset run.")
    ap.add_argument("--no-log", action="store_true",
                    help="Do not log a run that would be logged by default.")
    ap.add_argument("--note", default="",
                    help="One line for the run log: why this run was made.")
    args = ap.parse_args()
    if args.freeze and args.tier != "l4":
        ap.error("--freeze needs --tier l4: n73's baseline is frozen as published")

    chosen = datasets(args.all, args.dataset, args.tier)
    print(f"{len(chosen)} datasets")

    print(f"\n== profiles ({args.profile_jobs} at a time if fetching) ==")
    check_profile_provenance()
    profiles, unreadable = {}, []
    already = {p.stem for p in PROFILES.glob("*.txt")}
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
    fetched = set(profiles) - already
    whole = args.all or args.tier
    if whole and (args.force_profiles or fetched):
        # Only a full run can rewrite the manifest: a partial one would drop
        # every dataset it did not look at. A run that only filled gaps -- new
        # datasets added to the test set -- rewrites it too, keeping the
        # capture date of every profile it did not touch.
        write_provenance(profiles, unreadable)
        print(f"  provenance rewritten: {PROVENANCE}")
    elif args.force_profiles or fetched:
        print("  ! provenance NOT rewritten -- it describes the whole test set, so "
              "only --all or --tier can regenerate it.")

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

    # This benchmark is cell-type only: it exists to stay comparable to the
    # frozen baselines, and the frozen picks speak to no other field type.
    result = result["by_field_type"]["cell_type"]
    overall = result["overall"]
    by_tier = result.get("by_tier", {})
    baselines = (json.loads(scored.stdout).get("baseline") or {})
    for tier, block in by_tier.get("tiers", {}).items():
        _report(f"{tier} ({block['n']} scored)", block)
        base = (baselines.get(tier) or {}).get("overall")
        if base:
            delta = block["jaccard"]["mean"] - base["jaccard"]["mean"]
            print(f"  {baselines[tier]['source']}, same {base['n']} datasets: "
                  f"{base['jaccard']['mean']:.3f}  (delta {delta:+.3f})")
        else:
            print(f"  no frozen {tier} baseline yet")
    tiers = by_tier.get("tiers", {})
    if len(tiers) > 1:
        both = by_tier["all"]
        _report(f"all ({both['n']} unique CELLxGENE datasets, "
                f"{both['n_entries']} entries)", both)
        if {"n73", "l4"} <= set(tiers):
            gap = tiers["n73"]["jaccard"]["mean"] - tiers["l4"]["jaccard"]["mean"]
            print(f"  gap n73 - l4: {gap:+.3f}  (how much the picker leans on the "
                  "datasets it was developed against)")
    for tier, groups in by_tier.get("by_group", {}).items():
        if tier == "l4":
            print("\n== l4 by sheet ==")
            for group, g in sorted(groups.items(), key=lambda kv: kv[1]["jaccard"]):
                print(f"  {g['jaccard']:.3f}  ({g['n']:>2})  {group}")
    if by_tier.get("outside_test_set"):
        print(f"\n  not in the test set, scored but in no tier: "
              f"{', '.join(by_tier['outside_test_set'])}")

    print("\n== per dataset ==")
    for row in sorted(result["per_dataset"], key=lambda r: r["jaccard"]):
        flag = "  " if row["jaccard"] == 1.0 else "! "
        print(f"{flag}{row['dsid']}  J={row['jaccard']:.2f}")
        if row["missed_by_agent"]:
            print(f"      missed: {', '.join(row['missed_by_agent'])}")
        if row["agent_extras"]:
            print(f"      extra : {', '.join(row['agent_extras'])}")

    picker = _picker_provenance()
    picker["models_used"] = sorted({m for r in rows for m in r.get("models", [])})
    if any("picks" in r and not r.get("models") for r in rows):
        picker["models_note"] = "some picks came from a cache written before models were recorded"
    scope = (args.tier or ("all" if args.all else "subset")) if not args.dataset else "datasets"
    run_info = {
        "date": time.strftime("%Y-%m-%d"),
        "scope": scope,
        "command": shlex.join(["python3", "evals/benchmark.py", *sys.argv[1:]]),
        "note": args.note,
        "n_requested": len(chosen),
        "n_scored": overall["n"],
        "n_cached": sum(1 for r in rows if r.get("cached")),
        "unreadable": sorted(unreadable),
        "no_picks_returned": sorted(r["dsid"] for r in failed),
        "cost_usd": round(spent, 2),
        "picker": picker,
        "gold_snapshot": json.loads((EVAL_SRC / "obs_column_eval" / "data" / "curation"
                                     / "SOURCE.json").read_text())["commit"],
        "profiles": json.loads(PROVENANCE.read_text()).get("captured_by"),
        "results_dir": str(out_dir.relative_to(HERE.parent)) if out_dir.is_relative_to(HERE.parent)
                       else str(out_dir),
    }
    if args.freeze:
        freeze_baseline(args.tier, picks, result, run_info, chosen)

    if (args.log or args.all or args.tier) and not args.no_log:
        manifest = json.loads(_run([*EVAL_CLI, "datasets", "--all"]).stdout)
        record = build_record(run=run_info, cell_type=result, baselines=baselines,
                              manifest=manifest)
        print(f"\nlogged -> {write_run(record)}")

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
