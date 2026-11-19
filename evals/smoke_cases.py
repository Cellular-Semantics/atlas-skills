#!/usr/bin/env python3
"""Generate the plugin's `smoke` eval cases from the benchmark's light set.

    python3 evals/smoke_cases.py           # (re)write plugins/.../evals/smoke/
    python3 evals/smoke_cases.py --check   # exit 1 if they are out of date

One case per dataset in obs-column-eval's `subset.json`, in `claude plugin
eval` format. Each asks the plain question a user would ask, and grades the
`picks.json` the skill writes:

- every gold cell-type column is in `picks.cell_type` (one grader each),
- `picks.cell_type` holds exactly as many columns as the gold (so extras fail),
- each known trap column for that dataset is *not* picked,
- the portal's own `cell_type` fields are never picked.

The prompt says to work directly in the current directory, not a subdirectory:
each run starts in an empty workspace, and the file graders read `picks.json`
from its root. Without that, agents have worked under `$TMPDIR` or in a
`ds_<id>/` subfolder, and every file grader missed a correct answer.

A run's score is the fraction of graders passed, so it reads roughly as
recall and precision together. The exact Jaccard, per tier, stays in
`benchmark.py`: plugin eval has no code graders.

Generated, not hand-written, so the cases cannot drift from the gold set;
`test_smoke_cases.py` fails if they do.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "packages" / "obs-column-eval" / "src"))

from obs_column_eval.manifest import subset, with_ground_truth  # noqa: E402

OUT = ROOT / "plugins" / "author-annotation-columns" / "evals" / "smoke"
PICKS = "{ source: file, path: picks.json }"

#: Per dataset: the case name, and the columns a picker following its rules
#: must leave out, each with the rule that says so. Every trap must exist in
#: the dataset's obs (checked by the test).
CASES = {
    "e48806af-87d1-45ae-843a-c7ee06eac672": ("smoke-biccn-two-levels", {}),
    "0054013c-290b-437e-b98e-642aa77d6ebc": ("smoke-numeric-clusters", {
        "leiden": "rule 3: string-encoded integers are a cluster index",
        "louvain": "rule 3: string-encoded integers are a cluster index",
    }),
    "fb995261-472e-4ebc-99b0-d1136e1fad8a": ("smoke-constant-columns", {
        "Cell.class": "rule 4: constant across all cells",
        "Cell.group": "rule 4: constant across all cells",
        "Lineage": "rule 4: constant across all cells",
    }),
    "dabd979f-cc50-4526-81f3-8bc6c673ca36": ("smoke-label-beside-cluster-index", {
        "seurat_clusters": "rule 3: a numeric cluster index",
    }),
    "5668bd32-5e84-4708-b976-af6a902ed9a4": ("smoke-constant-lineage", {
        "Lineage": "rule 4 over rule 5: a lineage column, but constant here",
    }),
    "9bb8be38-d63f-4c8c-bf31-5ba078713315": ("smoke-three-level-hierarchy", {}),
    "4484426f-f83b-4bab-b06d-eb2e177aa031": ("smoke-breast-stroma-levels", {
        "level0_global": "rule 4: constant across all cells",
    }),
    "731ad926-5b60-45bf-85de-e32d037c1944": ("smoke-retina-fine-and-broad", {}),
}

#: The portal's standardised fields: never an author column.
PORTAL = ("cell_type", "cell_type_ontology_term_id")

#: Inside picks.json, the `picks.cell_type` array. `"cell_type":` with a colon
#: is the key; the same string in `requested` is followed by `,` or `]`.
ARRAY = r'"cell_type"\s*:\s*\['


def _in_array(col: str) -> str:
    return ARRAY + r'[^\]]*"' + re.escape(col) + '"'


def _exactly(n: int) -> str:
    if n == 0:
        return ARRAY + r"\s*\]"
    item = r'\s*"[^"]*"\s*'
    return ARRAY + item + ("," + item) * (n - 1) + r"\]"


def _grader(pattern: str, *, match: str | None = None, why: str) -> str:
    lines = ["---", "type: regex", f"target: {PICKS}", f"pattern: {json.dumps(pattern)}"]
    if match:
        lines.append(f"match: {match}")
    return "\n".join([*lines, "---", "", why, ""])


def render() -> dict[Path, str]:
    """Every file of the smoke suite, keyed by path."""
    truth = with_ground_truth(subset())
    if set(truth) != set(CASES):
        raise SystemExit(f"subset.json and CASES disagree: {sorted(set(truth) ^ set(CASES))}")
    files: dict[Path, str] = {}
    for dsid, (name, traps) in CASES.items():
        entry, gold = truth[dsid], truth[dsid]["curated"]
        case = OUT / name
        files[case / "prompt.md"] = "\n".join([
            "---",
            "tags: [smoke, cell-type]",
            "runs: 1",
            "max_turns: 40",
            "timeout_seconds: 1200",
            "allowed_tools: [Read, Glob, Grep, Skill, Agent, TodoWrite]",
            "---",
            "",
            f"Which obs columns in {entry['url']} hold the authors' own "
            "cell-type annotations? Work directly in the current directory, not in a "
            "subdirectory.",
            "",
        ])
        g = case / "graders"
        files[g / "picks-written.md"] = "\n".join([
            "---", "type: file_exists", "path: picks.json", "---", "",
            "The skill records its picks in `picks.json` before answering.", ""])
        files[g / "skill-fired.md"] = "\n".join([
            "---", "type: tool_used", "tool: Skill",
            "input_match: '\"skill\"\\s*:\\s*\"(?:[\\w-]+:)?author-annotation-columns\"'",
            "---", "",
            "The plugin's skill handled the request, not the agent on its own.", ""])
        for col in gold:
            files[g / f"picks-{_slug(col)}.md"] = _grader(
                _in_array(col), why=f"`{col}` is a curated author cell-type column (CL_KG).")
        files[g / "exact-count.md"] = _grader(
            _exactly(len(gold)),
            why=(f"`picks.cell_type` holds exactly {len(gold)} column(s), as curated: "
                 + (", ".join(f"`{c}`" for c in gold) if gold else "none; the right answer "
                    "is to pick nothing") + ". An extra pick fails this."))
        for col, rule in traps.items():
            files[g / f"not-{_slug(col)}.md"] = _grader(
                _in_array(col), match="not_contains", why=f"`{col}` is not picked: {rule}.")
        for col in PORTAL:
            files[g / f"not-portal-{_slug(col)}.md"] = _grader(
                _in_array(col), match="not_contains",
                why=f"`{col}` is the portal's standardised field, never an author column.")
    return files


def _slug(col: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", col.lower()).strip("-")


def main() -> int:
    files = render()
    stale = [p for p, text in files.items() if not p.exists() or p.read_text() != text]
    extra = [p for p in OUT.rglob("*.md") if p not in files] if OUT.exists() else []
    if "--check" in sys.argv:
        for p in stale + extra:
            print(f"out of date: {p.relative_to(ROOT)}")
        return 1 if stale or extra else 0
    for p in extra:
        p.unlink()
    for p, text in files.items():
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    print(f"{len(CASES)} cases, {len(files)} files -> {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
