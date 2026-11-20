"""Deterministic graders for the eval cases.

Pure functions over a captured run, so they are unit-tested without touching the
network or spending anything. `runner.py` does the subprocess work and calls in
here to score.

Each check is a dict with a `kind` and a `why` explaining what behaviour it pins.
A check that cannot be expressed deterministically belongs in the case's
`graders/criteria.md` instead, for an LLM grader to judge.

Keep this in step with the copy in cap_skills: the cases in both repos are
written for `claude plugin eval`, and a grader that drifts between repos means
cases stop being portable. Fixes belong in both.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

KINDS = ("command_matches", "command_not_matches", "answer_matches",
         "answer_not_matches", "answer_any_of", "numeric_in_range",
         "numeric_present")


#: Result text that means the harness stopped the run, not that the agent did badly.
#: Scoring these as failures buries a real regression under noise.
INFRA_MARKERS = ("spend limit", "usage limit", "rate limit", "overloaded",
                 "credit balance", "authentication_error", "please run /login")


@dataclass
class Run:
    """One agent run, reduced to what the graders look at."""

    answer: str = ""
    tool_calls: list[dict] = field(default_factory=list)
    turns: int = 0
    cost_usd: float = 0.0
    error: str | None = None
    infra_error: str | None = None

    @property
    def command_text(self) -> str:
        """Every tool input, JSON-serialised and concatenated.

        Graders match against this rather than against Bash commands alone, so a
        check catches the behaviour whether the agent shelled out or went through
        a tool with structured arguments.
        """
        return "\n".join(f'{c.get("name", "?")} {json.dumps(c.get("input", {}))}'
                         for c in self.tool_calls)


@dataclass
class Result:
    passed: bool
    check: dict
    detail: str

    @property
    def why(self) -> str:
        return self.check.get("why", "")


def _search(pattern: str, text: str):
    return re.search(pattern, text, re.IGNORECASE | re.MULTILINE)


def grade_one(check: dict, run: Run) -> Result:
    kind = check.get("kind")
    if kind not in KINDS:
        raise ValueError(f"unknown check kind {kind!r}; expected one of {', '.join(KINDS)}")

    if kind in ("command_matches", "command_not_matches"):
        hit = _search(check["pattern"], run.command_text)
        want = kind == "command_matches"
        return Result(bool(hit) == want, check,
                      f'{"found" if hit else "no"} tool call matching /{check["pattern"]}/')

    if kind in ("answer_matches", "answer_not_matches"):
        hit = _search(check["pattern"], run.answer)
        want = kind == "answer_matches"
        return Result(bool(hit) == want, check,
                      f'answer {"matches" if hit else "does not match"} /{check["pattern"]}/')

    if kind == "answer_any_of":
        # Word-bounded so PLCG2 does not match PLCG21 and TPM1 does not match
        # TPM10 -- gene symbols are prefixes of each other often enough to matter.
        hits = [p for p in check["patterns"]
                if _search(rf"\b{re.escape(p)}\b", run.answer)]
        need = check.get("min_hits", 1)
        return Result(len(hits) >= need, check,
                      f"{len(hits)}/{need} required: found {', '.join(hits) or 'none'}")

    if kind == "numeric_present":
        # Scan every number in the answer for one in range, rather than anchoring to
        # a label. Anchoring is brittle twice over: the agent may lay the result out
        # as a table either way round (cell types as rows, or genes as rows with cell
        # types as columns), and a nearby sentence can easily contain a *different*
        # percentage -- an early version of this grader matched "Tuft Progenitors,
        # well behind Cycling Macrophages (94.9%)". A distinctive value is enough.
        pattern = check.get("pattern", r"([\d]+\.[\d]+)\s*%")
        lo, hi = check["min"], check["max"]
        found = []
        for m in re.finditer(pattern, run.answer, re.IGNORECASE | re.MULTILINE):
            try:
                # Strip thousands separators. Agents write "1,679 cells", and a
                # grader that silently drops every comma-formatted number scores
                # a correct answer as having produced none.
                found.append(float(m.group(1).replace(",", "").rstrip(".")))
            except (ValueError, IndexError):
                continue
        hits = [v for v in found if lo <= v <= hi]
        return Result(bool(hits), check,
                      f'{"found " + str(hits[0]) if hits else "no value"} in {lo}-{hi} '
                      f'(saw {", ".join(str(v) for v in found[:8]) or "no numbers"})')

    # numeric_in_range
    m = _search(check["pattern"], run.answer)
    if not m or not m.groups():
        return Result(False, check, f'no number captured by /{check["pattern"]}/')
    try:
        value = float(m.group(1))
    except ValueError:
        return Result(False, check, f"captured {m.group(1)!r}, not a number")
    lo, hi = check["min"], check["max"]
    return Result(lo <= value <= hi, check, f"captured {value} (want {lo}-{hi})")


def classify_error(text: str) -> str | None:
    """Return the infrastructure marker this result text carries, if any."""
    low = (text or "").lower()
    return next((m for m in INFRA_MARKERS if m in low), None)


def grade(run: Run, checks: list[dict]) -> list[Result]:
    """Grade one run. A run that errored fails every check rather than scoring 0/0."""
    if run.error:
        return [Result(False, c, f"run failed: {run.error}") for c in checks]
    return [grade_one(c, run) for c in checks]


def score(results: list[Result]) -> float:
    return sum(r.passed for r in results) / len(results) if results else 0.0
