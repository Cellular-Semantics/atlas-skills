"""The rule ladder: first match wins, and no rung assigns on a similarity score.

The single most damaging failure this package exists to prevent is treating a
relevance rank as an identity. `upper reproductive tract` once resolved to
`lateral nasal gland`, `mid vertebrae` to `longissimus cervicis muscle`, and
`internal organs` to `mucosa of pharyngotympanic tube` -- every one of them by
taking the top hit of a fuzzy search. So the ladder here either matches a string
exactly against something the ontology actually offers, or it assigns nothing
and hands the string to a person with candidates attached.

Ambiguity is a refusal too. Two exact matches is not a tie to break; it is a
question the string cannot answer on its own.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .index import LexicalIndex, as_candidates
from .lexical import is_grouping_class, normalise


@dataclass
class Match:
    """One string's outcome. ``term_id is None`` is a legitimate, common result."""

    raw: str
    term_id: str | None = None
    term_name: str | None = None
    rule: str = "unmatched"
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
            "term_id": self.term_id,
            "term_name": self.term_name,
            "rule": self.rule,
            "match_type": self.match_type,
            "candidates": self.candidates,
            "rationale": self.rationale,
            "needs_review": self.needs_review,
            "flags": self.flags,
        }


def _unique_or_none(hits: list[dict[str, Any]]) -> dict[str, Any] | None:
    """One distinct term, or nothing. Several matches is an ambiguity, not a tie."""
    distinct = {h["id"]: h for h in hits}
    return next(iter(distinct.values())) if len(distinct) == 1 else None


def resolve(
    raw: str,
    index: LexicalIndex,
    *,
    placeholders: frozenset[str] = frozenset(),
) -> Match:
    """Run one string down the ladder against a local lexical index."""
    text = (raw or "").strip()
    if not text or text.lower() in placeholders:
        return Match(
            raw=raw,
            rule="placeholder",
            rationale="The value is empty or a recorded placeholder, not an annotation.",
        )

    # Rung 1 -- exact label. If the author wrote the ontology's own label, that
    # is the term, grouping class or not: they named it, we did not infer it.
    exact_labels = [e for e in index.normalised(text) if e.via == "label" and e.text.lower() == text.lower()]
    hit = _unique_or_none(as_candidates(exact_labels, index))
    if hit:
        return Match(
            raw=raw,
            term_id=hit["id"],
            term_name=hit["label"],
            rule="exact_label",
            match_type="exact",
            rationale=f"The string is the exact label of {hit['id']}.",
        )

    # Rung 2 -- exact synonym, exact scope only, grouping classes removed.
    #
    # The removal is load-bearing and was found the hard way. "skin" is a
    # *unique exact synonym* of `zone of skin`, a grouping class, while `skin of
    # body` -- the term every curator means -- carries it only as a related
    # synonym. Uniqueness alone would assign the wrong term with no hesitation.
    all_synonyms = [e for e in index.normalised(text) if e.via != "label"]
    exact_synonyms = [
        e
        for e in all_synonyms
        if e.via == "exact"
        and e.text.lower() == text.lower()
        and not is_grouping_class(index.labels.get(e.term_id))
    ]
    hit = _unique_or_none(as_candidates(exact_synonyms, index))
    if hit:
        return Match(
            raw=raw,
            term_id=hit["id"],
            term_name=hit["label"],
            rule="exact_synonym",
            match_type="exact",
            rationale=f"The string is an exact synonym of {hit['id']} ({hit['label']!r}).",
        )

    # Rung 3 -- normalised: same string once non-anatomical qualifiers, stopwords
    # and spelling variants are gone. "fetal liver tissue" is liver.
    normalised_hits = [
        e
        for e in index.normalised(text)
        if e.via in ("label", "exact") and not is_grouping_class(index.labels.get(e.term_id))
    ]
    hit = _unique_or_none(as_candidates(normalised_hits, index))
    if hit:
        return Match(
            raw=raw,
            term_id=hit["id"],
            term_name=hit["label"],
            rule="normalised_label",
            match_type="exact",
            rationale=(
                f"Normalises to {normalise(text)!r}, which is the "
                f"{'label' if hit['via'] == 'label' else 'exact synonym'} of {hit['id']}."
            ),
        )

    # Rung 4 -- same word set, any order. Weaker, so it is flagged rather than
    # trusted, and it still refuses when more than one term matches.
    token_hits = [
        e
        for e in index.tokens(text)
        if e.via in ("label", "exact") and not is_grouping_class(index.labels.get(e.term_id))
    ]
    hit = _unique_or_none(as_candidates(token_hits, index))
    if hit:
        return Match(
            raw=raw,
            term_id=hit["id"],
            term_name=hit["label"],
            rule="token_set",
            match_type="exact",
            rationale=f"Same word set as {hit['label']!r} after normalisation.",
            needs_review=True,
            flags=["token_set_match"],
        )

    # No rung fired. Everything the index offered becomes a candidate and the
    # string goes to a dossier with no ID on it.
    candidates = as_candidates(index.normalised(text) + index.tokens(text), index)
    return Match(
        raw=raw,
        rule="candidates_only",
        candidates=candidates,
        needs_review=True,
        rationale=(
            "No exact, normalised or token-set rule matched. "
            f"{len(candidates)} lexical candidate(s) attached for judgement; none assigned."
        ),
    )
