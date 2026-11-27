#!/usr/bin/env python3
"""Score the gene-id-curation skill on the 13 gic cases, or on an NLM-Gene tier.

    python3 evals/gene-identity/gic_benchmark.py                       # gic, all three variants
    python3 evals/gene-identity/gic_benchmark.py --variant baseline    # free: no agent
    python3 evals/gene-identity/gic_benchmark.py --variant quote-title --case 'gic-0*'
    python3 evals/gene-identity/gic_benchmark.py --dry-run             # print the prompts only
    python3 evals/gene-identity/gic_benchmark.py --set nlm-gene --tier l4 --variant quote-title

Sets: ``gic`` (the 13 cases in ``cases/``, answers in ``answers.json``) and
``nlm-gene`` (a tier of NLM-Gene test-split mentions from the
``gene-identity-eval`` package, which must be installed; scored by its
``metrics``, which adds per-stratum numbers and the lift over the lookup).

Variants (the gic README's three):

- ``baseline``: no agent. Scores the lookup's own answer (``resolver_baseline``
  in ``answers.json``) as if it were the record: the floor the skill must beat.
- ``quote``: the case's input minus ``title``.
- ``quote-title``: the case's input as written.

Each agent case is one headless ``claude -p`` run with this working tree's
plugin loaded (``--plugin-dir plugins/gene-identity``), in an empty temporary
directory. The agent is never given a path into this directory; a run whose
tool calls touch it is voided, not scored. Every non-dry run of an agent
variant is logged to ``runs/`` (see ``write_run``).

Scoring follows the gic README: a case passes when ``outcome`` matches; for
``GENE`` the ``ncbi_gene_id`` must be one of ``accept``; for
``NO_SINGLE_GENE`` and ``NOT_A_GENE_PRODUCT`` the ``kind`` must match.
``method`` and ``rationale`` are not scored.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import datetime as dt
import fnmatch
import json
import pathlib
import re
import subprocess
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PLUGIN = ROOT / "plugins" / "gene-identity"
CASES = HERE / "cases"
ANSWERS = HERE / "answers.json"
RUNS = HERE / "runs"
INDEX = RUNS / "README.md"

VARIANTS = ("baseline", "quote", "quote-title")
AGENT_VARIANTS = VARIANTS[1:]
#: The paths whose appearance in a tool call voids a run.
FORBIDDEN = re.compile(r"evals/gene-identity|answers\.json|gene-id-curation/answers"
                       r"|gene[-_]identity[-_]eval|nlm_gene|cases\.jsonl")

PROMPT = """Use the gene-id-curation skill on this name.

```json
{input}
```

Reply with the skill's output record as one JSON object in a ```json block. \
Do not write files."""

#: Keys every run file has; the tests hold committed run files to it.
#: ``set`` and ``tier`` came later: a run file without them is a gic run (files
#: are never edited after the fact).
REQUIRED_RUN_KEYS = {"date", "variant", "command", "n_cases", "n_scored", "passed",
                     "accuracy", "voided", "errors", "cost_usd", "provenance", "cases"}


# ── Cases ────────────────────────────────────────────────────────────────────


def load_cases(pattern: str = "*") -> dict[str, dict]:
    out = {}
    for f in sorted(CASES.glob("gic-*.json")):
        case = json.loads(f.read_text(encoding="utf-8"))
        if fnmatch.fnmatch(case["id"], pattern):
            out[case["id"]] = case
    return out


def load_answers() -> dict[str, dict]:
    return json.loads(ANSWERS.read_text(encoding="utf-8"))


def agent_input(case: dict, variant: str) -> dict:
    """What the agent sees: the case minus its id (and minus the title for
    ``quote``). ``quote_key`` is an evidencell storage key, not evidence."""
    out = {k: v for k, v in case.items() if k != "id"}
    if variant == "quote":
        out.pop("title", None)
    ev = out.get("evidence")
    if isinstance(ev, dict):
        out["evidence"] = {k: v for k, v in ev.items() if k != "quote_key"}
    return out


def prompt_for(case: dict, variant: str) -> str:
    return PROMPT.format(input=json.dumps(agent_input(case, variant), indent=2, ensure_ascii=False))


def load_set(name: str, pattern: str = "*", tier: str | None = None) -> dict[str, dict]:
    """``{id: {id, name, input, expected, baseline}}`` for either set: what the
    agent sees, what it is scored against, and the lookup's own answer."""
    if name == "gic":
        answers = load_answers()
        return {cid: {"id": cid, "name": c["name"], "input": c, "expected": answers[cid],
                      "baseline": baseline_record(answers[cid])}
                for cid, c in load_cases(pattern).items()}
    from gene_identity_eval import data, metrics

    cases = data.tier_cases(tier) if tier else data.cases()
    return {cid: {"id": cid, "name": c["input"]["name"], "input": c["input"],
                  "expected": c["expected"],
                  "baseline": metrics.baseline_record(c.get("resolver_baseline"))}
            for cid, c in cases.items() if fnmatch.fnmatch(cid, pattern)}


# ── Scoring (pure) ───────────────────────────────────────────────────────────


def score(record: dict | None, answer: dict) -> tuple[bool, str]:
    """``(passed, why)`` for one record against one answer."""
    if not isinstance(record, dict):
        return False, "no record"
    got, want = record.get("outcome"), answer["outcome"]
    if got != want:
        return False, f"outcome {got} (want {want})"
    if want == "GENE":
        accepted = {a["ncbi_gene_id"] for a in answer["accept"]}
        gid = record.get("ncbi_gene_id")
        if gid not in accepted:
            return False, (f"gene {gid or '?'} {record.get('symbol') or ''}".rstrip()
                           + f" (want {' or '.join(sorted(accepted))})")
        return True, f"gene {gid}"
    if want in ("NO_SINGLE_GENE", "NOT_A_GENE_PRODUCT") and answer.get("kind"):
        # NLM-Gene sets no kind (it doesn't say family vs complex): outcome only.
        if record.get("kind") != answer["kind"]:
            return False, f"kind {record.get('kind')} (want {answer['kind']})"
        return True, f"kind {answer['kind']}"
    return True, want


def baseline_record(answer: dict) -> dict:
    """The lookup's own answer as a record: a gene when it named one (by
    symbol: the baseline stores symbols), otherwise UNRESOLVED."""
    b = answer["resolver_baseline"]
    if b.get("gene"):
        by_symbol = {a["symbol"]: a["ncbi_gene_id"] for a in answer["accept"]}
        # A symbol outside `accept` has no ID here; None scores it as wrong.
        return {"outcome": "GENE", "symbol": b["gene"], "ncbi_gene_id": by_symbol.get(b["gene"])}
    return {"outcome": "UNRESOLVED", "kind": "AMBIGUOUS" if b.get("claimants") else "NO_MATCH"}


def extract_record(text: str) -> dict | None:
    """The last ```json block in a reply, or the last bare JSON object."""
    blocks = re.findall(r"```json\s*(.*?)```", text or "", re.DOTALL)
    candidates = list(reversed(blocks)) or [text or ""]
    for raw in candidates:
        try:
            obj = json.loads(raw.strip())
        except json.JSONDecodeError:
            continue
        if isinstance(obj, list) and obj and isinstance(obj[0], dict):
            obj = obj[0]
        if isinstance(obj, dict):
            return obj
    return None


def touched_forbidden(events: list[dict]) -> list[str]:
    """Tool calls in a stream-json transcript that reach into this directory."""
    hits = []
    for ev in events:
        if ev.get("type") != "assistant":
            continue
        for block in (ev.get("message") or {}).get("content") or []:
            if isinstance(block, dict) and block.get("type") == "tool_use":
                blob = json.dumps(block.get("input"))
                if FORBIDDEN.search(blob):
                    hits.append(f"{block.get('name')}: {blob[:160]}")
    return hits


def summarise(rows: list[dict]) -> dict:
    scored = [r for r in rows if r.get("passed") is not None]
    passed = sum(1 for r in scored if r["passed"])
    return {
        "n_cases": len(rows),
        "n_scored": len(scored),
        "passed": passed,
        "accuracy": round(passed / len(scored), 4) if scored else None,
        "voided": sorted(r["id"] for r in rows if r.get("voided")),
        "errors": sorted(r["id"] for r in rows if r.get("error")),
        "cost_usd": round(sum(r.get("cost_usd") or 0 for r in rows), 4),
    }


# ── Agent runs ───────────────────────────────────────────────────────────────


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True).stdout.strip()


def provenance() -> dict:
    out = {"plugin_version": json.loads(
        (PLUGIN / ".claude-plugin" / "plugin.json").read_text())["version"]}
    sha = _git("rev-parse", "--short", "HEAD")
    if sha:
        out["commit"] = sha
        if _git("status", "--porcelain", "--", "plugins/gene-identity", "packages/gene-identity"):
            out["uncommitted_changes"] = True
    version = subprocess.run(["claude", "--version"], capture_output=True, text=True).stdout.strip()
    if version:
        out["claude_code"] = version
    return out


def run_case(item: dict, variant: str, *, max_turns: int, timeout: int,
             model: str | None) -> dict:
    row: dict = {"id": item["id"], "name": item["name"]}
    cmd = ["claude", "-p", "--output-format", "stream-json", "--verbose",
           "--max-turns", str(max_turns), "--plugin-dir", str(PLUGIN),
           "--allowedTools", "Skill", "Bash", "Read"]
    if model:
        cmd += ["--model", model]
    with tempfile.TemporaryDirectory(prefix="gic-") as cwd:
        try:
            out = subprocess.run(cmd, input=prompt_for(item["input"], variant), cwd=cwd,
                                 capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            row["error"] = f"timed out after {timeout}s"
            return row
    events = []
    for line in out.stdout.splitlines():
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    result = next((e for e in reversed(events) if e.get("type") == "result"), None)
    if result is None:
        row["error"] = f"no result event (exit {out.returncode}): {out.stderr[:200]}"
        return row
    row.update(cost_usd=result.get("total_cost_usd") or 0.0, turns=result.get("num_turns"),
               models=sorted(result.get("modelUsage") or {}))
    if hits := touched_forbidden(events):
        row.update(voided=True, void_reason=hits[:3])
        return row
    if result.get("is_error"):
        row["error"] = f"agent error ({result.get('subtype')}, {result.get('num_turns')} turns)"
        return row
    record = extract_record(result.get("result") or "")
    row["record"] = record
    row["passed"], row["why"] = score(record, item["expected"])
    return row


# ── Run log ──────────────────────────────────────────────────────────────────


def write_run(record: dict) -> pathlib.Path:
    """One committed file per run, never overwritten, and the index rebuilt."""
    RUNS.mkdir(exist_ok=True)
    scope = "" if record.get("set", "gic") == "gic" else f"{record['set']}-{record.get('tier') or 'all'}-"
    stem = f"{record['date']}-{scope}{record['variant']}-{record['provenance'].get('commit', 'nogit')}"
    path = RUNS / f"{stem}.json"
    n = 2
    while path.exists():
        path = RUNS / f"{stem}-{n}.json"
        n += 1
    path.write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n")
    write_index()
    return path


def write_index() -> None:
    rows = []
    for f in sorted(RUNS.glob("*.json")):
        r = json.loads(f.read_text())
        p = r["provenance"]
        where = r.get("set", "gic") + (f" {r['tier']}" if r.get("tier") else "")
        rows.append(f"| [{f.stem}]({f.name}) | {where} | {r['variant']} | {r['passed']}/{r['n_scored']} "
                    f"| {r['accuracy']} | {len(r['voided'])} | {len(r['errors'])} "
                    f"| {r['cost_usd']} | {p.get('plugin_version')} | {p.get('commit')} |")
    INDEX.write_text(
        "# gene-id-curation benchmark runs\n\n"
        "Generated by `gic_benchmark.py`; do not edit. One file per run, never overwritten.\n\n"
        "| Run | Set | Variant | Passed | Accuracy | Voided | Errors | Cost (USD) | Plugin | Commit |\n"
        "|---|---|---|---|---|---|---|---|---|---|\n" + "\n".join(rows) + "\n")


# ── Main ─────────────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--set", choices=("gic", "nlm-gene"), default="gic", dest="case_set")
    ap.add_argument("--tier", help="nlm-gene only: a tier from gene-identity-eval, e.g. l4")
    ap.add_argument("--variant", choices=(*VARIANTS, "all"), default="all")
    ap.add_argument("--case", default="*", help="glob over case ids, e.g. 'gic-0*'")
    ap.add_argument("-j", "--jobs", type=int, default=4)
    ap.add_argument("--max-turns", type=int, default=25)
    ap.add_argument("--timeout", type=int, default=600, help="seconds per case")
    ap.add_argument("--model", help="passed to claude --model")
    ap.add_argument("--dry-run", action="store_true", help="print the prompts; run nothing")
    ap.add_argument("--no-log", action="store_true", help="do not write a run file")
    ap.add_argument("--note", default="", help="recorded in the run file")
    args = ap.parse_args(argv)

    cases = load_set(args.case_set, args.case, args.tier)
    if not cases:
        print(f"no case matches {args.case!r}", file=sys.stderr)
        return 1
    variants = VARIANTS if args.variant == "all" else (args.variant,)

    if args.dry_run:
        for v in variants:
            if v == "baseline":
                continue
            for item in cases.values():
                print(f"── {item['id']} [{v}] ──\n{prompt_for(item['input'], v)}\n")
        return 0

    prov = None
    for v in variants:
        if v == "baseline":
            rows = []
            for cid, item in cases.items():
                ok, why = score(item["baseline"], item["expected"])
                rows.append({"id": cid, "name": item["name"], "record": item["baseline"],
                             "passed": ok, "why": why})
        else:
            prov = prov or provenance()
            with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, args.jobs)) as pool:
                futures = {cid: pool.submit(run_case, item, v,
                                            max_turns=args.max_turns, timeout=args.timeout,
                                            model=args.model)
                           for cid, item in cases.items()}
                rows = [futures[cid].result() for cid in cases]
        summary = summarise(rows)
        if args.case_set == "nlm-gene":
            from gene_identity_eval import data, metrics

            all_cases = data.cases()
            summary["metrics"] = metrics.summarise(rows, all_cases)
            m = summary["metrics"]
            print(f"\n{v}: accuracy {m['accuracy']} vs lookup {m['baseline_accuracy']} "
                  f"(lift {m['lift']}); gene ID {m['gene_id_accuracy']}, family recall "
                  f"{m['family_recall']}")
            for s_name, s in m["per_stratum"].items():
                print(f"  {s_name:<18} {s['passed']}/{s['n']}  (lookup {s['baseline_accuracy']})")
        print(f"\n{v}: {summary['passed']}/{summary['n_scored']} passed"
              f" (voided {len(summary['voided'])}, errors {len(summary['errors'])},"
              f" ${summary['cost_usd']})")
        for r in rows:
            mark = "PASS" if r.get("passed") else ("VOID" if r.get("voided") else
                                                    "ERR " if r.get("error") else "FAIL")
            if args.case_set == "gic" or not r.get("passed"):
                print(f"  {mark} {r['id']} {r['name'][:24]:<24} {r.get('why') or r.get('error') or ''}")
        if v != "baseline" and not args.no_log:
            models = sorted({m for r in rows for m in r.get("models") or []})
            path = write_run({
                "date": dt.date.today().isoformat(), "set": args.case_set,
                "tier": args.tier, "variant": v,
                "command": " ".join(["python3", "evals/gene-identity/gic_benchmark.py",
                                     *(argv if argv is not None else sys.argv[1:])]),
                "note": args.note, **summary,
                "provenance": {**prov, "models": models, "case_glob": args.case},
                "cases": [{k: r.get(k) for k in ("id", "name", "passed", "why", "error",
                                                  "voided", "record", "cost_usd", "turns")}
                          for r in rows],
            })
            print(f"  logged {path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
