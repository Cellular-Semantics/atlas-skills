"""Developmental stage: parse to a day, then ask the ontology which term covers it.

The design point. HsapDv carries ``start_dpf`` / ``end_dpf`` -- days
post-fertilization -- on its Carnegie and week terms. So stage mapping is
numeric rather than lexical: parse whatever the author wrote into a day, or a
range of days, and query the windows. ``CS13``, ``13 pcw``, ``92 days`` and
``GW 15`` all become a number and then all take the same path, with no
hand-maintained conversion table between representations to drift.

Two steps, kept separate in the output on purpose. ``canonical`` is what we
decided the string *means*; ``term_id`` is what the ontology says that meaning's
term is. Conflating them hides which of the two was wrong.

Reference frames are the thing that will bite. Gestational age counts from the
last menstrual period, post-fertilization age from conception, about two weeks
apart. HsapDv's week terms are post-fertilization, so an unshifted gestational
value lands two weeks late -- and a study may write "gestational" while
reporting post-conception weeks. Every shift is flagged, and the frame is a
per-study question, never a per-string one.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from functools import lru_cache
from importlib import resources
from typing import Any

DAYS_PER_WEEK = 7
# Gestational (LMP) minus post-fertilization. The conventional figure.
LMP_OFFSET_WEEKS = 2

# Frames, and the strings that name them. Order matters in matching: the more
# specific spelling has to be tried first, or "weeks post conception" is read as
# a bare "weeks".
POST_FERTILIZATION = "post_fertilization"
GESTATIONAL = "gestational"
UNKNOWN_FRAME = "unknown"

_FRAME_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (POST_FERTILIZATION, re.compile(r"\b(pcw|wpc|dpc|dpf|pf|p\.?c\.?|post[\s-]*conception(al)?|"
                                    r"post[\s-]*fertili[sz]ation|post[\s-]*coit)\w*", re.I)),
    (GESTATIONAL, re.compile(r"\b(gw|ga|gestation\w*|lmp|menstrual)\b", re.I)),
]

_CARNEGIE = re.compile(r"\bcarnegie\s*(?:stage)?\s*0*(\d{1,2})\b|\bcs\s*0*(\d{1,2})\b", re.I)
_NUMBER = re.compile(r"(\d+(?:\.\d+)?)")
# The U+2013 alternative is deliberate: an en dash is how a spreadsheet
# autocorrects "13-14 pcw", and the value arrives that way.
_RANGE = re.compile(r"(\d+(?:\.\d+)?)\s*(?:-|\u2013|to)\s*(\d+(?:\.\d+)?)")

_WEEK_UNIT = re.compile(r"\b(w|wk|wks|week|weeks|pcw|wpc|gw)\b", re.I)
_DAY_UNIT = re.compile(r"\b(d|day|days|dpc|dpf)\b", re.I)
_MONTH_UNIT = re.compile(r"\b(m|mo|month|months)\b", re.I)
_YEAR_UNIT = re.compile(r"\b(y|yr|yrs|year|years)\b", re.I)

# Strings that record the absence of a value rather than a value.
NULL_VALUES = frozenset(
    {"", "na", "n/a", "nan", "none", "null", "unknown", "not applicable",
     "not available", "not collected", "not reported", "-", "--", "missing"}
)


@lru_cache(maxsize=1)
def stage_table() -> dict[str, dict[str, Any]]:
    """The vendored HsapDv table: label, synonyms, day window, granular flag.

    Carnegie terms carry ``start_dpf`` but mostly no ``end_dpf``, so their
    windows are closed here from the next stage's start. Without it a Carnegie
    value produces a half-open window that no containment test can use, and
    there are 24 of them.
    """
    raw = resources.files("ontomap.data").joinpath("hsapdv.json").read_text(encoding="utf-8")
    terms = json.loads(raw)["terms"]
    starts = sorted(
        (t["start_dpf"], k) for k, t in terms.items() if t.get("start_dpf") is not None
    )
    for position, (start, term_id) in enumerate(starts):
        term = terms[term_id]
        if term.get("end_dpf") is not None:
            continue
        later = next((s for s, _ in starts[position + 1 :] if s > start), None)
        if later is not None:
            term["end_dpf"] = later
            term["end_dpf_derived"] = True
    return terms


@dataclass
class StageMatch:
    raw: str
    canonical: str | None = None          # what we decided the string means
    frame: str = UNKNOWN_FRAME
    dpf_start: float | None = None        # inclusive
    dpf_end: float | None = None          # inclusive
    term_id: str | None = None
    term_name: str | None = None
    rule: str = "unmappable"
    match_type: str | None = None
    candidates: list[dict[str, Any]] = field(default_factory=list)
    rationale: str = ""
    needs_review: bool = False
    flags: list[str] = field(default_factory=list)

    @property
    def assigned(self) -> bool:
        return self.term_id is not None

    def to_dict(self) -> dict[str, Any]:
        return {
            "raw": self.raw,
            "canonical": self.canonical,
            "frame": self.frame,
            "dpf_start": self.dpf_start,
            "dpf_end": self.dpf_end,
            "term_id": self.term_id,
            "term_name": self.term_name,
            "rule": self.rule,
            "match_type": self.match_type,
            "candidates": self.candidates,
            "rationale": self.rationale,
            "needs_review": self.needs_review,
            "flags": self.flags,
        }


def detect_frame(text: str) -> str:
    for frame, pattern in _FRAME_PATTERNS:
        if pattern.search(text):
            return frame
    return UNKNOWN_FRAME


def _carnegie_term(number: int) -> tuple[str, dict[str, Any]] | None:
    wanted = {f"carnegie stage {number:02d}", f"carnegie stage {number}", f"cs{number}"}
    for term_id, term in stage_table().items():
        names = {(term.get("label") or "").lower(), *(s.lower() for s in term.get("synonyms", []))}
        if names & wanted:
            return term_id, term
    return None


# A term spanning more than five weeks cannot place a sample at a stage: it is
# a period label. HsapDv's own `granular_stage` subset is the intended marker
# for this but does not cover the Carnegie terms -- all 23 of them are flagged
# false -- and for an early embryo a Carnegie term is the most precise thing
# there is. Day 20 is Carnegie stage 09 (19-22 dpf) and the subset filter alone
# threw that away, so width decides and the subset flag only ever adds terms.
MAX_GRANULAR_WIDTH_DAYS = 35.0

# HsapDv also carries LMP-based terms ("fourth LMP month stage", 77-105 dpf).
# Everything here is converted to days *post-fertilization*, so an LMP term is
# on a different reference frame even when the arithmetic happens to contain
# the value -- which it does: widening the granularity filter promoted
# "fourth LMP month stage" over the week terms for a 13-14 pcw range. Assigning
# it would be the two-week frame error of §9.6 arriving by a new route. They
# stay available as candidates, because a study reporting gestational age may
# legitimately want one, but that is a per-study decision and not a default.
_LMP_LABEL = re.compile(r"\bLMP\b", re.I)


def terms_covering(
    day_start: float, day_end: float | None = None, *, granular_only: bool = True
) -> list[dict[str, Any]]:
    """Every HsapDv term whose day window covers the value, most specific first.

    Windows abut rather than nest, so a boundary day legitimately matches two
    terms: day 91 is both the end of the 13th week and the start of the 14th.
    That is returned as two candidates, not silently resolved -- the convention
    is a project decision and this is where it becomes visible.
    """
    end = day_start if day_end is None else day_end
    out = []
    for term_id, term in stage_table().items():
        start, finish = term.get("start_dpf"), term.get("end_dpf")
        if start is None or finish is None:
            continue
        if granular_only:
            if _LMP_LABEL.search(term.get("label") or ""):
                continue
            if not (term.get("granular") or (finish - start) <= MAX_GRANULAR_WIDTH_DAYS):
                continue
        if start <= day_start and end <= finish:
            out.append(
                {
                    "id": term_id,
                    "label": term.get("label"),
                    "start_dpf": start,
                    "end_dpf": finish,
                    "width": finish - start,
                    "definition": term.get("definition"),
                }
            )
    out.sort(key=lambda t: (t["width"], t["id"]))
    return out


def parse(
    raw: str,
    *,
    unit: str | None = None,
    frame: str | None = None,
    boundary: str = "during",
) -> StageMatch:
    """Parse one stage or age string into a day window and an HsapDv term.

    ``unit`` folds in a sibling unit column -- bare numeric ages are otherwise
    unmappable, and the unit routinely lives in its own column.
    ``frame`` overrides frame detection, which is how a per-study decision gets
    applied to every row of that study.
    ``boundary`` picks the reading of "N weeks": ``during`` the Nth week (days
    (N-1)*7 to N*7) or ``completed`` N whole weeks (day N*7).
    """
    flags: list[str] = []
    text = (raw or "").strip()
    if text.lower() in NULL_VALUES:
        return StageMatch(raw=raw, rule="null", rationale="Explicitly no value recorded.")

    combined = f"{text} {unit}".strip() if unit else text
    detected = frame or detect_frame(combined)

    # Carnegie first: it is unambiguous, needs no conversion, and the ontology
    # carries the CS numbers as exact synonyms.
    carnegie = _CARNEGIE.search(text)
    if carnegie:
        number = int(carnegie.group(1) or carnegie.group(2))
        found = _carnegie_term(number)
        if not found:
            return StageMatch(
                raw=raw,
                canonical=f"Carnegie stage {number}",
                rule="carnegie_unknown",
                needs_review=True,
                rationale=f"Parsed as Carnegie stage {number}, which HsapDv has no term for.",
            )
        term_id, term = found
        return StageMatch(
            raw=raw,
            canonical=f"Carnegie stage {number}",
            frame=POST_FERTILIZATION,
            dpf_start=term.get("start_dpf"),
            dpf_end=term.get("end_dpf"),
            term_id=term_id,
            term_name=term.get("label"),
            rule="carnegie",
            match_type="exact",
            rationale=f"Carnegie stage {number} is {term_id} ({term.get('label')!r}); no conversion needed.",
        )

    # More than one number and not a range: a pooled value, which no single term
    # can represent. Recording that it is pooled matters more than the numbers.
    span = _RANGE.search(combined)
    numbers = _NUMBER.findall(combined)
    if not numbers:
        return StageMatch(
            raw=raw,
            rule="unmappable",
            needs_review=True,
            rationale="No Carnegie stage and no number to parse.",
        )
    if len(numbers) > 2 or (len(numbers) == 2 and not span):
        return StageMatch(
            raw=raw,
            canonical=", ".join(numbers),
            frame=detected,
            rule="multi_value",
            needs_review=True,
            flags=["pooled"],
            rationale=(
                "Names more than one stage, so it is a pooled sample and no single term "
                "applies. Split the sample or resolve per library."
            ),
        )

    low = float(span.group(1)) if span else float(numbers[0])
    high = float(span.group(2)) if span else low

    if _DAY_UNIT.search(combined):
        unit_name, start, end = "day", low, high
    elif _WEEK_UNIT.search(combined):
        # A frame is not a unit. "post-conception" tells you where the scale
        # starts, not what it counts in, and guessing weeks from it turned a
        # bare "13" into a confident term in testing.
        unit_name = "week"
        weeks_low, weeks_high = low, high
        if detected == GESTATIONAL:
            weeks_low -= LMP_OFFSET_WEEKS
            weeks_high -= LMP_OFFSET_WEEKS
            flags.append("gestational_shift_applied")
        if boundary == "completed":
            start, end = weeks_low * DAYS_PER_WEEK, weeks_high * DAYS_PER_WEEK
        else:
            start, end = (weeks_low - 1) * DAYS_PER_WEEK, weeks_high * DAYS_PER_WEEK
    elif _YEAR_UNIT.search(combined) or _MONTH_UNIT.search(combined):
        return StageMatch(
            raw=raw,
            canonical=f"{low} {'year' if _YEAR_UNIT.search(combined) else 'month'}(s)",
            frame=detected,
            rule="postnatal",
            needs_review=True,
            flags=["postnatal"],
            rationale=(
                "An age in months or years is postnatal. If this atlas is prenatal, the "
                "scope filter is letting through samples it should not."
            ),
        )
    else:
        return StageMatch(
            raw=raw,
            canonical=numbers[0],
            frame=detected,
            rule="no_unit",
            needs_review=True,
            flags=["unit_missing"],
            rationale=(
                f"Parsed the number {numbers[0]} but found no unit, in the value or in a "
                "declared unit column. A bare number cannot be placed on any scale."
            ),
        )

    if detected == UNKNOWN_FRAME:
        flags.append("frame_assumed_post_fertilization")

    covering = terms_covering(start, end)
    canonical = f"{low if low == high else f'{low}-{high}'} {unit_name}(s) {detected}"

    if not covering:
        # A span wider than one week has no granular term by construction. The
        # coarser terms that do cover it are the honest answer, offered as
        # candidates rather than assigned: rolling a two-week range up to
        # "fetal stage" is a real loss of resolution and a curator's call.
        coarser = terms_covering(start, end, granular_only=False)
        return StageMatch(
            raw=raw, canonical=canonical, frame=detected, dpf_start=start, dpf_end=end,
            rule="no_granular_term" if coarser else "no_covering_term",
            candidates=coarser, needs_review=True, flags=flags,
            rationale=(
                f"Days {start}-{end} post-fertilization are covered by no granular HsapDv "
                f"term. {len(coarser)} coarser term(s) do cover the span; rolling up to one "
                "loses resolution, so none is assigned here."
                if coarser else
                f"Days {start}-{end} post-fertilization fall outside every HsapDv window. "
                "Only 64 of 260 HsapDv terms carry a day window at all."
            ),
        )

    # Exactly the same window as one term is the strongest possible result.
    exact = [t for t in covering if t["start_dpf"] == start and t["end_dpf"] == end]
    if len(exact) == 1:
        term = exact[0]
        return StageMatch(
            raw=raw, canonical=canonical, frame=detected, dpf_start=start, dpf_end=end,
            term_id=term["id"], term_name=term["label"], rule="dpf_window",
            match_type="exact", candidates=covering, flags=flags,
            needs_review=bool(flags),
            rationale=(
                f"Days {start}-{end} post-fertilization are exactly the window of "
                f"{term['id']} ({term['label']!r})."
            ),
        )

    narrowest = covering[0]
    tied = [t for t in covering if t["width"] == narrowest["width"]]
    if len(tied) > 1:
        return StageMatch(
            raw=raw, canonical=canonical, frame=detected, dpf_start=start, dpf_end=end,
            rule="boundary_ambiguous", candidates=covering, needs_review=True,
            flags=[*flags, "boundary"],
            rationale=(
                f"Days {start}-{end} sit on a window boundary and match "
                f"{', '.join(t['label'] for t in tied)} equally. Windows abut rather than "
                "nest, so this is a convention question, not a lookup failure."
            ),
        )
    return StageMatch(
        raw=raw, canonical=canonical, frame=detected, dpf_start=start, dpf_end=end,
        term_id=narrowest["id"], term_name=narrowest["label"], rule="dpf_window",
        match_type="broad_by_stage_window", candidates=covering,
        flags=flags, needs_review=True,
        rationale=(
            f"Days {start}-{end} fall inside {narrowest['id']} ({narrowest['label']!r}, "
            f"{narrowest['start_dpf']}-{narrowest['end_dpf']} dpf) but do not fill it."
        ),
    )
