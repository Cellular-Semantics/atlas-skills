"""Sex -> PATO. Trivial to map, and a disambiguator for tissue.

The one rule that matters: a value naming more than one sex maps to **no term**
-- one row cannot have two sexes -- and that fact is recorded explicitly rather
than left as an empty field.

The distinction is not pedantic. Downstream, sex specialisation of a tissue term
("reproductive system" -> "female reproductive system") must be blocked for
pooled libraries. A blocker that reads the *mapped* field sees an empty value
for exactly the pooled rows that most need blocking, and lets them through. So
``mixed`` is a state of its own, and the guard reads the raw text.
"""

from __future__ import annotations

from .ladder import Match

FEMALE = "PATO:0000383"
MALE = "PATO:0000384"

_FEMALE = frozenset({"female", "f", "woman", "girl", "xx", "pato:0000383"})
_MALE = frozenset({"male", "m", "man", "boy", "xy", "pato:0000384"})
_UNKNOWN = frozenset(
    {"", "na", "n/a", "nan", "none", "null", "unknown", "unspecified", "not recorded",
     "not collected", "not reported", "mixed", "pooled", "both", "-", "--"}
)

_SPLIT = str.maketrans({",": " ", ";": " ", "/": " ", "|": " ", "+": " "})


def resolve(raw: str) -> Match:
    text = (raw or "").strip().lower()
    if text in _UNKNOWN:
        mixed = text in {"mixed", "pooled", "both"}
        return Match(
            raw=raw,
            rule="mixed" if mixed else "unknown",
            flags=["sex_mixed"] if mixed else [],
            needs_review=mixed,
            rationale=(
                "The value states the library pools both sexes, so no single PATO term "
                "applies. Recorded as mixed, not as absent."
                if mixed
                else "No sex recorded."
            ),
        )

    words = {w for w in text.translate(_SPLIT).split() if w}
    names_female = bool(words & _FEMALE) or text in _FEMALE
    names_male = bool(words & _MALE) or text in _MALE

    if names_female and names_male:
        return Match(
            raw=raw,
            rule="mixed",
            flags=["sex_mixed"],
            needs_review=True,
            rationale=(
                f"{raw!r} names both sexes, so this is a pooled library and no single PATO "
                "term applies. Guards downstream must read this flag, not the empty term."
            ),
        )
    if names_female:
        return Match(raw=raw, term_id=FEMALE, term_name="female", rule="exact_label",
                     match_type="exact", rationale=f"{raw!r} names female.")
    if names_male:
        return Match(raw=raw, term_id=MALE, term_name="male", rule="exact_label",
                     match_type="exact", rationale=f"{raw!r} names male.")
    return Match(
        raw=raw, rule="unmatched", needs_review=True,
        rationale=f"{raw!r} is not a recognised sex value.",
    )
