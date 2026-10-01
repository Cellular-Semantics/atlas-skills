"""Several author columns, one target field.

Atlases routinely record the same thing more than once -- `Organ` and
`Organ_part`, a stage text column and a numeric age column -- and the second
column is usually finer than the first. Which is the cheapest evidence in the
whole pipeline and the easiest to throw away.

So the columns are not a precedence list. They are resolved independently and
then compared *structurally*: if the refinement is a descendant of the primary,
take the refinement, and the descendant edge is the proof that it is genuinely
finer rather than merely different. If neither subsumes the other, that is a
conflict in the source data, and inventing a winner would bury a real curation
finding under a tidy answer.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .ladder import Match
from .ubergraph import PART_OF, SUBCLASS_OF, Ubergraph

# Rules that record an absence rather than an outcome. When one column is empty
# and another tried and failed, the failure is the informative result: reporting
# "null" from the empty primary hides that the other column parsed to 623 dpf
# and found no term, which is the thing a curator needs to see.
ABSENT_RULES = frozenset({"placeholder", "null", "unknown"})


@dataclass
class Reconciled:
    match: Match
    sources: dict[str, Match] = field(default_factory=dict)
    agreement: str = "single"   # single | agree | refined | conflict | one_sided
    winner: str | None = None   # which source column the answer came from

    def to_dict(self) -> dict[str, Any]:
        return {
            **self.match.to_dict(),
            "agreement": self.agreement,
            "winner_column": self.winner,
            "sources": {name: m.to_dict() for name, m in self.sources.items()},
        }


def reconcile(
    matches: dict[str, Match],
    ubergraph: Ubergraph,
    *,
    via: tuple[str, ...] = (SUBCLASS_OF, PART_OF),
) -> Reconciled:
    """Combine one field's per-column matches into a single answer.

    ``matches`` is ordered: the first key is the primary column, the rest are
    refinements.
    """
    if not matches:
        raise ValueError("nothing to reconcile")
    names = list(matches)
    assigned = {n: m for n, m in matches.items() if m.assigned}

    if len(matches) == 1:
        return Reconciled(match=matches[names[0]], sources=dict(matches),
                          agreement="single", winner=names[0])

    if not assigned:
        informative = [n for n in names if matches[n].rule not in ABSENT_RULES]
        chosen = informative[0] if informative else names[0]
        primary = matches[chosen]
        merged = Match(
            raw=primary.raw,
            rule=primary.rule,
            flags=list(primary.flags),
            candidates=[c for m in matches.values() for c in m.candidates],
            needs_review=True,
            rationale=(
                f"No column resolved to a term; reporting the outcome from {chosen!r}, "
                "the first column that had a value to interpret. Candidates from all "
                "columns attached."
            ),
        )
        return Reconciled(
            match=merged, sources=dict(matches), agreement="one_sided", winner=chosen
        )

    if len({m.term_id for m in assigned.values()}) == 1:
        winner_name = next(iter(assigned))
        winner = assigned[winner_name]
        if len(assigned) == len(matches):
            winner.rationale += (
                f" All {len(assigned)} source columns ({', '.join(assigned)}) agree."
            )
            return Reconciled(match=winner, sources=dict(matches), agreement="agree",
                              winner=winner_name)
        return Reconciled(match=winner, sources=dict(matches), agreement="one_sided",
                          winner=winner_name)

    # Two or more different terms. Ask the ontology whether one is inside another.
    ids = [m.term_id for m in assigned.values()]
    ancestors = ubergraph.ancestors(ids, via=via)
    finest = None
    for name, candidate in assigned.items():
        others = [i for i in ids if i != candidate.term_id]
        if all(other in ancestors.get(candidate.term_id, set()) for other in others):
            finest = (name, candidate)
            break

    if finest is None:
        primary_name = names[0]
        conflict = Match(
            raw=matches[primary_name].raw,
            rule="column_conflict",
            candidates=[m.to_dict() for m in assigned.values()],
            needs_review=True,
            flags=["column_conflict"],
            rationale=(
                "Source columns resolved to terms where none subsumes the others: "
                + "; ".join(f"{n}={m.term_id} ({m.term_name!r})" for n, m in assigned.items())
                + ". No precedence rule is applied -- a disagreement between author columns "
                "is a finding about the source data, not a tie to break."
            ),
        )
        return Reconciled(match=conflict, sources=dict(matches), agreement="conflict",
                          winner=None)

    name, winner = finest
    coarser = [f"{n}={m.term_id}" for n, m in assigned.items() if m.term_id != winner.term_id]
    winner.rule = f"refined_by_{name}"
    winner.rationale += (
        f" Taken from column {name!r} because {winner.term_id} is a descendant of "
        f"{', '.join(coarser)} -- finer, and provably the same anatomy."
    )
    return Reconciled(match=winner, sources=dict(matches), agreement="refined", winner=name)
