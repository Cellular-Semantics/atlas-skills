#!/usr/bin/env python3
"""Run real tissue descriptions through the installed map-to-ontology skill.

    python3 evals/ontology-mapping/run-batch.py --slice evals/ontology-mapping/slice-20.txt
    python3 evals/ontology-mapping/run-batch.py --units U002,U089 --dry-run

This is not a scorer. The descriptions it runs have no expected answers, so
nothing here decides whether a mapping is right -- it produces mappings and the
reasoning behind them for a person to review. `check.py` is the scorer, and it
needs a gold set that this run is meant to help create.

Isolation comes from `evals/runner.py`: a fresh temporary directory per unit, so
no project CLAUDE.md and no .claude/skills are in scope and the only thing
answering is the installed plugin. Check which build that is before trusting a
run -- `claude plugin list` -- because a plugin installed from a marketplace copy
does not change when the working tree does.
"""
from __future__ import annotations

import argparse
import csv
import json
import pathlib
import subprocess
import sys
import tempfile
import time

HERE = pathlib.Path(__file__).parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT / "evals"))


SHEET = ROOT / "docs" / "fetal-tissue-review-sheet.tsv"

ALLOWED = ["Skill", "Bash(uvx:*)", "Bash(python3:*)", "Read", "Write"]

PROMPT = """\
Map the tissue described by each of these {n} records to a term in the Uberon
anatomy ontology.

The records come from a review table of human fetal single-cell datasets. Each
field is reproduced exactly as it appears in its source column; `tissue_obs` and
`tissue_dataset_metadata` are separate columns and their key-value pairs are the
submitter's own, not a controlled vocabulary. The records are unrelated to each
other except that all are human fetal tissue.

{records}

Work them as the map-to-ontology skill directs, one record at a time.

**As soon as you finish each record, emit its report** as a fenced ```json
block, before starting the next one. Do not save them all until the end: a
report written when the record is finished survives an interruption, and one
held back does not.

```json
{{"unit_id": "U001", "curie": "UBERON:...", "label": "...", "unresolved": false,
  "why_this_not_that": "...",
  "input_read_as": "what you took the input to be, which field you searched and why",
  "moves_used": ["..."], "answered_by": "...",
  "rejected": [{{"curie": "...", "label": "...", "reason": "..."}}],
  "validators_flagged": [], "unaccounted": [], "unavailable": []}}
```

Set `unresolved` to true, with `curie` null, for any record that cannot honestly
be mapped to one term.
"""


def record_text(row: dict) -> str:
    lines = [f"=== {row['unit_id']} ===",
             f"publication_id           {row['publication_id']}"]
    for col in ("tissue_obs", "tissue_dataset_metadata", "tissue_study_level", "tissue_caveat"):
        val = (row[col] or "").strip()
        if val and val != "{}":
            lines.append(f"{col:<24} {val}")
    lines.append(f"{'libraries':<24} {row['libraries']}  ({row['donors']} donors, {row['n_cells']} cells)")
    if row["stages"]:
        lines.append(f"{'stages':<24} {row['stages']}")
    return "\n".join(lines)


def extract(text: str) -> dict:
    """Every report block in the text, keyed by unit_id.

    The agent emits one block per record as it finishes rather than one at the
    end, so a run cut short still yields the records it completed. Blocks are
    read out of the raw assistant text, which means this works on a partial
    transcript as well as a finished reply.
    """
    out = {}
    for chunk in text.split("```"):
        body = chunk[4:] if chunk.startswith("json") else chunk
        body = body.strip()
        if not body.startswith("{"):
            continue
        try:
            obj = json.loads(body)
        except json.JSONDecodeError:
            continue
        if "unit_id" in obj and "curie" in obj:
            out[obj["unit_id"]] = obj
        else:                       # tolerate a keyed-by-unit_id bundle too
            for k, v in obj.items():
                if isinstance(v, dict) and "curie" in v:
                    out[k] = v
    return out


def stream_invoke(prompt: str, name: str, allowed: list[str], timeout: int,
                  max_turns: int, transcript: pathlib.Path, on_report=None):
    """Run one agent process, writing the transcript as it arrives.

    runner.invoke captures output and writes it only after the process exits,
    which is fine for a 90-second single record and blind for a batch. Here the
    transcript is flushed per line and reports are surfaced as they appear, so a
    long batch can be watched and a killed one can still be salvaged.
    """
    cmd = ["claude", "-p", "--output-format", "stream-json", "--verbose",
           "--max-turns", str(max_turns), "--allowedTools", *allowed]
    answer_parts, tool_calls, result = [], [], {}
    with tempfile.TemporaryDirectory(prefix=f"eval-{name}-") as cwd, \
         transcript.open("w") as tf:
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, text=True, cwd=cwd)
        proc.stdin.write(prompt)
        proc.stdin.close()
        seen = set()
        deadline = time.time() + timeout
        try:
            for line in proc.stdout:
                tf.write(line)
                tf.flush()
                if time.time() > deadline:
                    proc.kill()
                    result.setdefault("error", f"timed out after {timeout}s")
                    break
                try:
                    ev = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if ev.get("type") == "assistant":
                    for b in (ev.get("message") or {}).get("content") or []:
                        if b.get("type") == "text":
                            answer_parts.append(b.get("text") or "")
                            for uid in extract("".join(answer_parts)):
                                if uid not in seen:
                                    seen.add(uid)
                                    if on_report:
                                        on_report(uid)
                        elif b.get("type") == "tool_use":
                            tool_calls.append({"name": b.get("name"),
                                               "input": b.get("input", {})})
                elif ev.get("type") == "result":
                    result = {"turns": ev.get("num_turns") or 0,
                              "cost": ev.get("total_cost_usd") or 0.0,
                              "error": "agent error" if ev.get("is_error") else None}
                    answer_parts.append(ev.get("result") or "")
        finally:
            proc.wait(timeout=30)
    return {"answer": "".join(answer_parts), "tool_calls": tool_calls,
            "turns": result.get("turns", 0), "cost_usd": result.get("cost", 0.0),
            "error": result.get("error")}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--slice", type=pathlib.Path)
    ap.add_argument("--units")
    ap.add_argument("--out", type=pathlib.Path, default=HERE / "runs" / "batch.json")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--max-cost-usd", type=float, default=15.0)
    ap.add_argument("--timeout", type=int, default=900,
                help="per record; multiplied by batch size")
    ap.add_argument("--batch-size", type=int, default=5,
                    help="records per agent process. The skill text and the "
                         "per-session release check are re-read on every turn of "
                         "every process, so batching amortises both; measured at "
                         "~31k of context per turn against ~3k of oq output for a "
                         "whole single-record run.")
    a = ap.parse_args()

    ids = []
    if a.slice:
        ids += [ln.strip() for ln in a.slice.read_text().splitlines() if ln.strip()]
    if a.units:
        ids += [u.strip() for u in a.units.split(",") if u.strip()]
    rows = {r["unit_id"]: r for r in csv.DictReader(SHEET.open(), delimiter="\t")}
    missing = [u for u in ids if u not in rows]
    if missing:
        print(f"unknown unit(s): {missing}")
        return 2

    a.out.parent.mkdir(parents=True, exist_ok=True)
    transcripts = a.out.parent / "transcripts"
    transcripts.mkdir(exist_ok=True)

    results, spent = [], 0.0
    groups = [ids[i:i + a.batch_size] for i in range(0, len(ids), a.batch_size)]
    for gi, group in enumerate(groups, 1):
        recs = [rows[u] for u in group]
        prompt = PROMPT.format(n=len(recs), records="\n\n".join(record_text(r) for r in recs))
        if a.dry_run:
            print(f"=== batch {gi} ({len(recs)} records)\n{prompt}\n")
            continue
        if spent >= a.max_cost_usd:
            print(f"stopping before batch {gi}: spent ${spent:.2f} of ${a.max_cost_usd:.2f}")
            break
        name = group[0] if len(group) == 1 else f"{group[0]}-x{len(group)}"
        # Scale with batch size: batched records share one conversation whose
        # context grows as it goes, so later records are slower than earlier
        # ones and a flat timeout kills the tail.
        timeout = a.timeout * len(recs) if a.batch_size > 1 else a.timeout
        def progress(uid, _seen=[], _n=len(recs)):  # noqa: B006 - per-batch counter
            _seen.append(uid)
            print(f"      · {uid} reported ({len(_seen)}/{_n})", flush=True)

        run = stream_invoke(prompt, name, ALLOWED, timeout,
                            25 + 15 * len(recs), transcripts / f"{name}.jsonl",
                            on_report=progress)
        spent += run["cost_usd"] or 0.0
        parsed = extract(run["answer"] or "")
        oq = [t for t in run["tool_calls"]
              if t["name"] == "Bash" and "oq " in str(t["input"].get("command", ""))]
        for row in recs:
            uid = row["unit_id"]
            report = parsed.get(uid)
            results.append({
                "unit_id": uid, "publication_id": row["publication_id"],
                "record": {c: row[c] for c in ("tissue_obs", "tissue_dataset_metadata",
                                               "tissue_study_level", "tissue_caveat")},
                "report": report, "error": run["error"],
                "batch_size": len(recs), "turns": run["turns"],
                # Cost is shared across whatever the batch actually reported, so
                # a per-record figure stays comparable with single-record runs.
                "cost_usd": (run["cost_usd"] or 0.0) / max(len(parsed), 1),
                "oq_calls": [t["input"].get("command", "") for t in oq],
                "raw_answer": run["answer"] if report is None else None,
            })
        a.out.write_text(json.dumps(results, indent=1))
        got = sum(1 for r in recs if parsed.get(r["unit_id"]))
        print(f"[batch {gi:>2}/{len(groups)}] {name:<14} {got}/{len(recs)} reported  "
              f"{run['turns']:>3} turns  ${run['cost_usd'] or 0:.2f}  "
              f"(${(run['cost_usd'] or 0)/max(got,1):.2f}/record)"
              + (f"  ERROR {run['error']}" if run['error'] else ""), flush=True)

    if not a.dry_run:
        print(f"\n{len(results)} units, ${spent:.2f}; reports in {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
