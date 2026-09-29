#!/usr/bin/env python3
"""Run the eval cases against the installed author-celltype-columns plugin.

This is scaffolding, not a product: `claude plugin eval` does this properly
(including a no-plugin ablation arm and LLM graders) but is in early access and
unavailable on this machine. The case layout here — `prompt.md` plus
`graders/criteria.md` — is the layout `plugin eval` expects, so the cases migrate
unchanged; only this file and `checks.json` are throwaway.

Each case runs in a fresh temporary directory so nothing but the user-scope
plugin is in scope: no project CLAUDE.md, no `.claude/skills`.

    python3 evals/runner.py                       # every case, one run each
    python3 evals/runner.py --case 'tuft-*'        # a subset
    python3 evals/runner.py --runs 3 --tag degs
    python3 evals/runner.py --dry-run             # print prompts, spend nothing

These cases read real h5ads from the CELLxGENE CDN and cost real money
(~$0.20-0.50 per run), so the default is one run per case and `--max-cost-usd`
aborts if a suite runs away.

For picker *accuracy* against the curated gold set -- a different question, with
metrics rather than checks -- see `benchmark.py`.
"""
from __future__ import annotations

import argparse
import fnmatch
import json
import pathlib
import re
import subprocess
import sys
import tempfile
import time

from graders import Run, classify_error, grade, score

HERE = pathlib.Path(__file__).parent
CASES = HERE / "cases"
# Task is allowed because the picker runs as a sub-agent; without it the skill
# cannot complete and every case fails for the wrong reason.
DEFAULT_ALLOWED = ["Skill", "Task", "Bash(uvx:*)", "Bash(python3:*)", "Read", "Write"]


def load_cases(case_glob: str | None, tags: list[str]) -> list[dict]:
    cases = []
    for checks_file in sorted(CASES.glob("*/checks.json")):
        spec = json.loads(checks_file.read_text())
        spec["name"] = spec.get("name", checks_file.parent.name)
        spec["dir"] = checks_file.parent
        spec["prompt"] = (checks_file.parent / "prompt.md").read_text().strip()
        if case_glob and not fnmatch.fnmatch(spec["name"], case_glob):
            continue
        if tags and not (set(tags) & set(spec.get("tags", []))):
            continue
        cases.append(spec)
    return cases


def invoke(prompt: str, spec: dict, transcript_path: pathlib.Path) -> Run:
    """One headless agent run in a clean directory."""
    allowed = spec.get("allowed_tools", DEFAULT_ALLOWED)
    cmd = ["claude", "-p", "--output-format", "stream-json", "--verbose",
           "--max-turns", str(spec.get("max_turns", 25)),
           "--allowedTools", *allowed]
    with tempfile.TemporaryDirectory(prefix=f"eval-{spec['name']}-") as cwd:
        try:
            proc = subprocess.run(cmd, input=prompt, capture_output=True, text=True,
                                  cwd=cwd, timeout=spec.get("timeout_seconds", 900))
        except subprocess.TimeoutExpired:
            return Run(error=f'timed out after {spec.get("timeout_seconds", 900)}s')

    transcript_path.write_text(proc.stdout)
    run = Run()
    for line in proc.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("type") == "assistant":
            for block in event["message"].get("content", []):
                if block.get("type") == "tool_use":
                    run.tool_calls.append({"name": block.get("name"),
                                           "input": block.get("input", {})})
        elif event.get("type") == "result":
            run.answer = event.get("result") or ""
            run.turns = event.get("num_turns") or 0
            run.cost_usd = event.get("total_cost_usd") or 0.0
            if event.get("is_error"):
                # A spend/rate limit is the harness stopping us, not the skill
                # failing. Mark it so the suite reports it apart from real failures.
                marker = classify_error(run.answer)
                run.error = "agent reported an error result"
                if marker:
                    run.infra_error = f"{marker}: {run.answer[:120]}"
    if not run.answer and not run.error:
        run.error = f"no result event (exit {proc.returncode}): {proc.stderr[:200]}"
    return run


#: The plugin that owns the skills and the sub-agent these cases exercise.
#: Named explicitly rather than taken as "the repo's plugin": each skill now
#: installs on its own, so a user with a different one installed would
#: otherwise satisfy a guard that checks nothing relevant.
REQUIRED_PLUGIN = "author-celltype-columns"

#: What the cases need to be present. Bump alongside that plugin's version.
EXPECTED_PLUGIN_VERSION = "0.3.0"

INSTALL_HINT = (
    "  claude plugin marketplace add Cellular-Semantics/atlas-skills --scope user\n"
    f"  claude plugin install {REQUIRED_PLUGIN}@atlas-skills --scope user")


def installed_plugins() -> list[dict]:
    """Parse `claude plugin list` into {name, version, scope} rows."""
    out = subprocess.run(["claude", "plugin", "list"], capture_output=True, text=True).stdout
    rows, current = [], None
    for line in out.splitlines():
        stripped = line.strip()
        if "@" in stripped and not stripped.startswith(("Version:", "Scope:", "Status:")):
            # Strip whatever bullet the CLI prefixes the name with, rather than
            # one specific glyph -- it is decoration and liable to change.
            current = {"name": re.sub(r"^\W+", "", stripped)}
            rows.append(current)
        elif current is not None and ":" in stripped:
            key, _, value = stripped.partition(":")
            current[key.strip().lower()] = value.strip()
    return rows


def check_plugin_installed() -> None:
    """Insist on a *user-scope* install, at the version the cases expect.

    Scope matters here and the obvious check gets it wrong. Each case runs in a
    fresh temp directory, deliberately, so nothing but user scope is visible --
    a project- or local-scope install lives in the repo, the temp dir is not in
    the repo, and every case would silently run with no plugin and fail for the
    wrong reason. Matching on the plugin name alone waves that setup through.
    """
    rows = [r for r in installed_plugins()
            if r["name"].startswith(f"{REQUIRED_PLUGIN}@")]
    user = [r for r in rows if r.get("scope") == "user"]
    if not user:
        other = ", ".join(f'{r.get("scope")} scope' for r in rows)
        sys.exit(f"{REQUIRED_PLUGIN} is not installed at user scope"
                 + (f" (found at: {other} -- the cases run in a temp directory and "
                    "cannot see those)" if rows else "")
                 + ". These cases test the published plugin:\n" + INSTALL_HINT)
    version = user[0].get("version", "?")
    if version != EXPECTED_PLUGIN_VERSION:
        sys.exit(f"{REQUIRED_PLUGIN} {version} is installed at user scope, but these "
                 f"cases expect {EXPECTED_PLUGIN_VERSION}. A pushed tag plus a "
                 "marketplace update is needed before an edit shows up here:\n"
                 "  claude plugin marketplace update atlas-skills\n"
                 f"  claude plugin install {REQUIRED_PLUGIN}@atlas-skills --scope user")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--case", help="Filter cases by name glob")
    ap.add_argument("--tag", action="append", default=[], help="Filter by tag (repeatable)")
    ap.add_argument("--runs", type=int, help="Runs per case (default: the case's own)")
    ap.add_argument("--max-cost-usd", type=float, default=8.0,
                    help="Abort once the suite has spent this much (default 8)")
    ap.add_argument("--threshold", type=float, default=1.0,
                    help="Exit 1 if any case scores below this (default 1.0)")
    ap.add_argument("--output-dir", help="Where to write results (default evals/results/<ts>)")
    ap.add_argument("--dry-run", action="store_true", help="Print the prompts and exit")
    args = ap.parse_args()

    cases = load_cases(args.case, args.tag)
    if not cases:
        sys.exit("No cases matched.")

    if args.dry_run:
        for spec in cases:
            print(f'=== {spec["name"]}  tags={",".join(spec.get("tags", []))} '
                  f'checks={len(spec["checks"])}')
            print(spec["prompt"], "\n")
        return 0

    check_plugin_installed()
    out_dir = pathlib.Path(args.output_dir or HERE / "results" / time.strftime("%Y%m%d-%H%M%S"))
    out_dir.mkdir(parents=True, exist_ok=True)

    spent, aggregate, failures, infra = 0.0, [], [], []
    for spec in cases:
        runs = args.runs or spec.get("runs", 1)
        for i in range(runs):
            if spent >= args.max_cost_usd:
                print(f"\n! cost ceiling ${args.max_cost_usd} reached; stopping early")
                break
            label = f'{spec["name"]}#{i + 1}'
            print(f"\n=== {label}")
            run = invoke(spec["prompt"], spec, out_dir / f"{label.replace('#', '-')}.jsonl")
            spent += run.cost_usd
            results = grade(run, spec["checks"])
            s = score(results)
            for r in results:
                print(f'  {"PASS" if r.passed else "FAIL"}  {r.check["kind"]:20s} {r.detail}')
                if not r.passed and r.why:
                    print(f"        pins: {r.why}")
            print(f'  score {s:.2f}  turns {run.turns}  ${run.cost_usd:.2f}'
                  + (f"  ERROR {run.error}" if run.error else ""))
            aggregate.append({"case": spec["name"], "run": i + 1, "score": s,
                              "turns": run.turns, "cost_usd": run.cost_usd,
                              "error": run.error, "infra_error": run.infra_error,
                              "answer": run.answer,
                              "checks": [{"kind": r.check["kind"], "passed": r.passed,
                                          "detail": r.detail, "why": r.why}
                                         for r in results]})
            if run.infra_error:
                infra.append(label)
            elif s < args.threshold:
                failures.append(label)

    (out_dir / "aggregate-result.json").write_text(
        json.dumps({"spent_usd": round(spent, 4), "runs": aggregate}, indent=2))
    print(f"\n{len(aggregate)} runs, ${spent:.2f} spent -> {out_dir}")
    if infra:
        print(f'! not scored -- the harness stopped these, rerun them: {", ".join(infra)}')
    if failures:
        print(f'below threshold {args.threshold}: {", ".join(failures)}')
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
