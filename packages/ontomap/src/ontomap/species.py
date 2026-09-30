"""Species -> NCBITaxon. Trivial in itself, and the gate for everything else.

It runs first because it decides which stage ontology applies and, in a later
version, which anatomy is admissible at all. v1 accepts human and stops on
anything else rather than half-working: the stage tables here are HsapDv and the
morphology map is human, so a mouse row would be mapped by machinery that was
never meant for it.
"""

from __future__ import annotations

from .ladder import Match

HUMAN = "NCBITaxon:9606"

_HUMAN_STRINGS = frozenset(
    {"human", "homo sapiens", "h. sapiens", "hsapiens", "homo-sapiens",
     "human being", "9606", "ncbitaxon:9606", "homo sapiens sapiens"}
)


def resolve(raw: str) -> Match:
    text = (raw or "").strip().lower()
    if not text:
        return Match(raw=raw, rule="placeholder", rationale="No species recorded.")
    if text in _HUMAN_STRINGS:
        return Match(
            raw=raw,
            term_id=HUMAN,
            term_name="Homo sapiens",
            rule="exact_label",
            match_type="exact",
            rationale=f"{raw!r} names Homo sapiens.",
        )
    return Match(
        raw=raw,
        rule="unsupported_species",
        needs_review=True,
        flags=["non_human"],
        rationale=(
            f"{raw!r} is not human. This version maps human data only: the stage tables "
            "are HsapDv and the normalisation is human-specific, so mapping a non-human "
            "row here would apply the wrong machinery rather than none."
        ),
    )
