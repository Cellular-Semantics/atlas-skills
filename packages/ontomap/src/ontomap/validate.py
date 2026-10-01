"""The gates. Every id the pipeline emits goes through them, and a failure blocks.

Validation gates the pipeline, not the reviewer. A failing structural claim
stops the row; it does not become a warning on an otherwise-shipped table,
because a warning on a plausible wrong id is indistinguishable from noise and
will be read as one.

Gates run on *every* id: primary terms, rejected alternatives, per-part terms,
common ancestors, candidate lists. An id that was never going to be used is
still an id someone may read as evidence.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .ols import Ols
from .ubergraph import PART_OF, SUBCLASS_OF, Ubergraph

EXPECTED_PREFIX = {
    "tissue": "UBERON",
    "stage": "HsapDv",
    "sex": "PATO",
    "species": "NCBITaxon",
    "disease": ("MONDO", "PATO"),   # PATO:0000461 normal is the healthy convention
}


@dataclass
class GateResult:
    gate: str
    term_id: str
    passed: bool
    detail: str

    def to_dict(self) -> dict[str, Any]:
        return {"gate": self.gate, "term_id": self.term_id, "passed": self.passed,
                "detail": self.detail}


def check_terms(
    terms: list[dict[str, Any]],
    ols: Ols,
    *,
    field: str | None = None,
) -> list[GateResult]:
    """ID_RESOLVES, LABEL_MATCHES, NOT_OBSOLETE and PREFIX_EXPECTED.

    ``terms`` is a list of ``{"id": ..., "name": ...}``. The name is what the
    pipeline recorded; the gate asks OLS what that id's label actually is and
    compares. Closing the loop from the other direction is what catches an
    invented id -- and a copy-paste slip, and a stale snapshot.
    """
    results: list[GateResult] = []
    expected = EXPECTED_PREFIX.get(field) if field else None
    for entry in terms:
        term_id, recorded = entry.get("id"), entry.get("name")
        if not term_id:
            continue

        if expected:
            allowed = (expected,) if isinstance(expected, str) else expected
            ok = term_id.split(":", 1)[0] in allowed
            results.append(
                GateResult(
                    "PREFIX_EXPECTED", term_id, ok,
                    f"{term_id} is {'in' if ok else 'not in'} {'/'.join(allowed)} for field {field!r}",
                )
            )

        live = ols.lookup(term_id)
        if live is None:
            results.append(GateResult("ID_RESOLVES", term_id, False,
                                      f"{term_id} does not resolve in its own ontology"))
            continue
        results.append(GateResult("ID_RESOLVES", term_id, True, f"{term_id} resolves"))
        results.append(
            GateResult("NOT_OBSOLETE", term_id, not live["obsolete"],
                       f"{term_id} is {'obsolete' if live['obsolete'] else 'current'}")
        )
        if recorded:
            ok = (live["label"] or "").strip().lower() == recorded.strip().lower()
            results.append(
                GateResult(
                    "LABEL_MATCHES", term_id, ok,
                    f"recorded {recorded!r}; the ontology says {live['label']!r}"
                    if not ok else f"{term_id} is {live['label']!r}",
                )
            )
    return results


def check_broad_matches(
    claims: list[dict[str, Any]],
    ubergraph: Ubergraph,
    *,
    via: tuple[str, ...] = (SUBCLASS_OF, PART_OF),
) -> list[GateResult]:
    """BROAD_IS_ANCESTOR and NOT_SELF: is the generalisation real?

    "Broad match" must not become a licence for an unrelated term. Each claim
    names an exemplar -- a specific structure the string certainly covers -- and
    this asks the ontology whether the assigned term actually subsumes it.

    It earns its keep on plausible-but-unasserted pairs. `viscus` was once
    proposed for "internal organs" with liver as the exemplar; UBERON does not
    assert liver under viscus, though it does assert pancreas. The term was
    defensible and the exemplar was wrong, and only a query could tell.

    Where the specific structure has no term at all, no exemplar can exist. Such
    a claim must set ``specific_term_missing`` and is skipped here rather than
    passed silently -- it belongs on the new-term request list.
    """
    results: list[GateResult] = []
    checkable = [
        c for c in claims
        if c.get("term_id") and c.get("exemplar_specific_term_id")
        and not c.get("specific_term_missing")
    ]
    for claim in claims:
        if claim.get("specific_term_missing"):
            results.append(
                GateResult(
                    "BROAD_IS_ANCESTOR", claim.get("term_id", "?"), True,
                    "skipped: the specific structure has no term, so no exemplar can "
                    "exist. Flagged for a new-term request.",
                )
            )
    if not checkable:
        return results

    pairs = [(c["term_id"], c["exemplar_specific_term_id"]) for c in checkable]
    holds = ubergraph.is_ancestor_of(pairs, via=via)
    for claim in checkable:
        broad, exemplar = claim["term_id"], claim["exemplar_specific_term_id"]
        results.append(
            GateResult(
                "NOT_SELF", broad, broad != exemplar,
                f"{broad} is {'the exemplar itself' if broad == exemplar else 'not the exemplar'}",
            )
        )
        ok = holds.get((broad, exemplar), False)
        results.append(
            GateResult(
                "BROAD_IS_ANCESTOR", broad, ok,
                f"{broad} {'subsumes' if ok else 'does NOT subsume'} the exemplar {exemplar}",
            )
        )
    return results


def summarise(results: list[GateResult]) -> dict[str, Any]:
    failures = [r for r in results if not r.passed]
    by_gate: dict[str, dict[str, int]] = {}
    for result in results:
        counts = by_gate.setdefault(result.gate, {"passed": 0, "failed": 0})
        counts["passed" if result.passed else "failed"] += 1
    return {
        "checked": len(results),
        "failed": len(failures),
        "by_gate": by_gate,
        "failures": [f.to_dict() for f in failures],
    }
