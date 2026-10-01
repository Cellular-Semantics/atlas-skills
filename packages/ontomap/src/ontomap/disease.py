"""Disease -> MONDO, with "normal" going to PATO by convention.

Mostly deterministic: MONDO's labels and exact synonyms cover most recorded
diagnoses. What is left needs judgement, and it is a small, recognisable set --
abbreviations (`IPF`), descriptions rather than diagnoses (`COVID-19 positive`),
and grain, where an author names a subtype MONDO records at a different level.
Those go to a dossier.

The healthy case is a convention, not a lookup: CELLxGENE records absence of
disease as PATO:0000461 `normal`, and a search for "healthy" in MONDO will
happily return something else.
"""

from __future__ import annotations

from .index import LexicalIndex
from .ladder import Match
from .ladder import resolve as ladder_resolve

NORMAL = "PATO:0000461"

_NORMAL_STRINGS = frozenset(
    {"normal", "healthy", "control", "healthy control", "non-diseased", "nondiseased",
     "no disease", "none", "unaffected", "wild type", "wildtype", "wt", "na", "n/a",
     "not applicable", "-"}
)

# Recorded as a disease field but describing the sample, not a diagnosis.
_NOT_A_DIAGNOSIS = frozenset({"unknown", "not reported", "not collected", "nan", "null", ""})


def resolve(raw: str, index: LexicalIndex) -> Match:
    text = (raw or "").strip().lower()

    if text in _NOT_A_DIAGNOSIS:
        return Match(
            raw=raw, rule="unknown", needs_review=False,
            rationale="No disease state recorded. Absent, which is not the same as normal.",
        )

    if text in _NORMAL_STRINGS:
        return Match(
            raw=raw, term_id=NORMAL, term_name="normal", rule="normal_convention",
            match_type="exact",
            rationale=(
                f"{raw!r} states the absence of disease. Tier 1 records that as PATO:0000461 "
                "`normal`, not as a MONDO term -- a MONDO search for 'healthy' returns "
                "something else entirely."
            ),
        )

    match = ladder_resolve(raw, index)
    if match.assigned and not match.term_id.startswith("MONDO:"):
        # The index is built per prefix, so this should not happen; if it ever
        # does, a non-MONDO id in a disease column is worth refusing over.
        return Match(
            raw=raw, rule="wrong_namespace", candidates=[match.to_dict()], needs_review=True,
            rationale=f"Matched {match.term_id}, which is not a MONDO term.",
        )
    return match
