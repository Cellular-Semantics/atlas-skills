"""Tissue -> UBERON, under the context the other fields establish.

This is the field the whole package is shaped around, because the right term
depends on things the tissue string does not contain: the sample's age decides
whether a mature organ term or its embryonic precursor is correct, the sex field
decides whether a sex-neutral term may be specialised, and the disease field
decides whether a qualifier in the string belongs in ``sampled_site_condition``
instead of the anatomy.

Order within the field is deliberate and specialisation comes *before*
developmental substitution. A precursor usually has no sex-specific sibling, so
substituting first and specialising second silently drops the sex information
every time.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from . import ehdaa2
from .index import LexicalIndex
from .ladder import Match
from .ladder import resolve as ladder_resolve
from .lexical import is_grouping_class, is_uninformative, split_composite
from .ubergraph import PART_OF, SUBCLASS_OF, Ubergraph

# Roots whose descendants are not places a sample came from. When the deepest
# thing several parts share is one of these, the parts span organ systems and
# the roll-up has destroyed the anatomy -- the point at which §5.4 says refuse.
#
# `anatomical system` alone is not enough, and the gap is not obvious: UBERON
# does not classify `endocrine system` under it. Liver and thymus share
# `endocrine system`, which arrives via `non-connected functional system` and
# `disconnected anatomical group` instead -- names that say plainly these are
# sets of things that work together, not contiguous structures.
NOT_A_PLACE_ROOTS = frozenset(
    {
        "UBERON:0000467",  # anatomical system
        "UBERON:0015203",  # non-connected functional system
        "UBERON:0034923",  # disconnected anatomical group
    }
)

# Strings recording how a sample was prepared, not where it came from. They
# belong in tissue_type or cell_enrichment, and mapping them to anatomy at all
# is the error.
NOT_A_TISSUE = re.compile(
    r"\b(organoid|cell\s*line|ipsc|esc|cultured?|culture|in\s*vitro|sorted|"
    r"facs|magnetic\s*bead|cd\d+\s*[-+]|enriched|depleted|dissociated\s*cells?|"
    r"single\s*cell\s*suspension)\b",
    re.I,
)

# Placeholders are matched against the *whole* string, not as substrings.
# A preparation word qualifies whatever else the string says -- "sorted liver"
# is still a sort gate -- but "liver and unknown region" names a real organ and
# an unresolved one, which is a composite to decompose, not a placeholder.
PLACEHOLDER_ONLY = re.compile(
    r"^\s*(not\s*applicable|unknown|n/?a|none|null|missing|other|-{1,2})\s*$", re.I
)

# Qualifiers naming a condition of the site rather than the site.
_CONDITION_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("diseased", re.compile(r"\b(tumou?r|tumou?rous|cancer(ous)?|carcinoma|malignant|"
                            r"lesional|inflamed|fibrotic|diseased|affected)\b", re.I)),
    ("adjacent", re.compile(r"\b(adjacent|peri[-\s]?tumou?ral|non[-\s]?lesional|"
                            r"tumou?r[-\s]?adjacent|matched\s+normal)\b", re.I)),
    ("healthy", re.compile(r"\b(healthy|normal|unaffected|control)\b", re.I)),
]

_FEMALE_ANATOMY = re.compile(
    r"\b(ovar(y|ian)|uter(us|ine)|vagina\w*|cervix|cervical\s+os|endometri\w+|"
    r"fallopian|oviduct|placenta\w*|decidua\w*|myometri\w+|clitor\w+|labia\w*)\b", re.I
)
_MALE_ANATOMY = re.compile(
    r"\b(test(is|es|icular)|prostat\w+|epididym\w+|vas\s+deferens|seminal\s+vesicle|"
    r"scrot\w+|penis|penile|foreskin|prepuce)\b", re.I
)


@dataclass
class Context:
    """What the other fields established about this row, before tissue is mapped."""

    taxon: str | None = None
    dpf_start: float | None = None
    dpf_end: float | None = None
    sex_term: str | None = None
    sex_mixed: bool = False
    disease_term: str | None = None
    disease_raw: str | None = None

    @property
    def has_age(self) -> bool:
        return self.dpf_start is not None


@dataclass
class TissueResult:
    match: Match
    tissue_type: str | None = None
    sampled_site_condition: str | None = None
    term_mature_id: str | None = None
    term_mature_name: str | None = None
    parts_free_text: str | None = None
    exemplar_specific_term_id: str | None = None
    evidence: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            **self.match.to_dict(),
            "tissue_type": self.tissue_type,
            "sampled_site_condition": self.sampled_site_condition,
            "term_mature_id": self.term_mature_id,
            "term_mature_name": self.term_mature_name,
            "parts_free_text": self.parts_free_text,
            "exemplar_specific_term_id": self.exemplar_specific_term_id,
            "evidence": self.evidence,
        }


def strip_condition(raw: str) -> tuple[str, str | None]:
    """Remove a condition qualifier from the string, returning both halves."""
    condition = None
    text = raw
    for name, pattern in _CONDITION_PATTERNS:
        if pattern.search(text):
            condition = condition or name
            text = pattern.sub(" ", text)
    return re.sub(r"\s{2,}", " ", text).strip(" ,;-"), condition


def resolve(
    raw: str,
    index: LexicalIndex,
    ubergraph: Ubergraph,
    context: Context | None = None,
) -> TissueResult:
    """Run one tissue string through the gate, the ladder and the context modifiers."""
    context = context or Context()
    text = (raw or "").strip()

    if not text:
        return TissueResult(match=Match(raw=raw, rule="placeholder",
                                        rationale="No tissue recorded."))

    if PLACEHOLDER_ONLY.match(text):
        return TissueResult(
            match=Match(
                raw=raw, rule="placeholder",
                rationale=f"{raw!r} records the absence of a value, not a site.",
            )
        )

    if NOT_A_TISSUE.search(text):
        return TissueResult(
            match=Match(
                raw=raw, rule="not_a_tissue", needs_review=True, flags=["not_a_tissue"],
                rationale=(
                    f"{raw!r} records a sort gate, culture condition or placeholder rather "
                    "than an anatomical site. It belongs in tissue_type or cell_enrichment; "
                    "mapping it to anatomy at all would be the error."
                ),
            ),
            tissue_type="cell culture",
        )

    stripped, condition = strip_condition(text)
    result = _resolve_anatomy(raw, stripped, index, ubergraph)
    result.sampled_site_condition = _site_condition(condition, context)

    if result.match.assigned:
        result = _specialise_by_sex(result, stripped, index, ubergraph, context)
        result = _substitute_developmental(result, ubergraph, context)
    return result


def _site_condition(condition: str | None, context: Context) -> str | None:
    """Combine the string's qualifier with the disease field. Either can supply it."""
    if condition:
        return condition
    if context.disease_term and context.disease_term != "PATO:0000461":
        return "diseased"
    if context.disease_term == "PATO:0000461":
        return "healthy"
    return None


def _resolve_anatomy(
    raw: str, text: str, index: LexicalIndex, ubergraph: Ubergraph
) -> TissueResult:
    direct = ladder_resolve(text, index)
    if direct.assigned:
        direct.raw = raw
        return TissueResult(match=direct)

    parts = split_composite(text)
    if len(parts) > 1:
        return _resolve_composite(raw, parts, index, ubergraph)

    direct.raw = raw
    return TissueResult(match=direct)


def _resolve_composite(
    raw: str, parts: list[str], index: LexicalIndex, ubergraph: Ubergraph
) -> TissueResult:
    """Several sites in one string: roll up to what contains all of them, or refuse."""
    resolved = {part: ladder_resolve(part, index) for part in parts}
    assigned = {p: m for p, m in resolved.items() if m.assigned}

    if len(assigned) < len(parts):
        unresolved = [p for p in parts if p not in assigned]
        return TissueResult(
            match=Match(
                raw=raw, rule="composite_unresolved", needs_review=True,
                candidates=[c for m in resolved.values() for c in m.candidates],
                flags=["composite"],
                rationale=(
                    f"Names {len(parts)} sites, of which {', '.join(repr(u) for u in unresolved)} "
                    "did not resolve. A roll-up over an incomplete decomposition would be "
                    "a generalisation over the wrong set."
                ),
            ),
            evidence={"parts": {p: m.to_dict() for p, m in resolved.items()}},
        )

    ids = [m.term_id for m in assigned.values()]
    if len(set(ids)) == 1:
        winner = next(iter(assigned.values()))
        winner.raw = raw
        winner.rationale += " Every named part resolved to the same term."
        return TissueResult(match=winner, parts_free_text="; ".join(parts))

    # Containment, not classification. `part_of` only: a reasoner has already
    # folded the is_a steps into the part_of closure, so cornea still reaches
    # eyeball, while `subdivision of oviduct` -- which only ever arrives by is_a
    # -- drops out, and so does `endocrine gland`, which is a kind of thing
    # rather than a place liver and thymus both sit inside.
    ancestors = ubergraph.common_ancestors(ids, via=(PART_OF,))
    systems = _systems_among([a["id"] for a in ancestors], ubergraph)
    usable = [
        a for a in ancestors
        if not is_uninformative(a["label"])
        and not is_grouping_class(a["label"])
        and a["id"] not in systems
    ]

    if not usable:
        return TissueResult(
            match=Match(
                raw=raw, rule="composite_spans_systems", needs_review=True,
                candidates=ancestors[:10], flags=["composite", "spans_organ_systems"],
                rationale=(
                    "The parts share no common ancestor that names a place a sample could "
                    "come from -- only organ systems, whole-body terms or grouping classes. "
                    "The parts span organ systems, so a roll-up would destroy the anatomy: "
                    "a pooled multi-organ sample has to be split or resolved per library."
                ),
            ),
            parts_free_text="; ".join(parts),
            evidence={"parts": {p: m.to_dict() for p, m in assigned.items()},
                      "rejected_ancestors": ancestors[:10]},
        )

    best = usable[0]
    tied = [a for a in usable if a["information_content"] == best["information_content"]]
    if len(tied) > 1:
        # Information content is a better ranking than depth but it does tie:
        # `oviduct` and `subdivision of oviduct` score identically. Grouping
        # classes are already gone by here, so a remaining tie is genuine.
        return TissueResult(
            match=Match(
                raw=raw, rule="composite_ambiguous", needs_review=True,
                candidates=tied, flags=["composite"],
                rationale=(
                    f"{len(tied)} candidate ancestors are equally specific: "
                    + ", ".join(f"{a['label']} ({a['id']})" for a in tied)
                    + ". Equally specific is not a tie to break by ordering."
                ),
            ),
            parts_free_text="; ".join(parts),
        )

    return TissueResult(
        match=Match(
            raw=raw, term_id=best["id"], term_name=best["label"],
            rule="composite", match_type="broad_by_partonomy",
            candidates=usable[:5], needs_review=True, flags=["composite", "rolled_up"],
            rationale=(
                f"Names {len(parts)} sites ({', '.join(parts)}); {best['id']} "
                f"({best['label']!r}) is the most specific term containing all of them. "
                "This is a real loss of resolution -- the parts are preserved verbatim."
            ),
        ),
        parts_free_text="; ".join(parts),
        exemplar_specific_term_id=ids[0],
        evidence={"parts": {p: m.to_dict() for p, m in assigned.items()}},
    )


def _systems_among(ids: list[str], ubergraph: Ubergraph) -> set[str]:
    """Which of these terms *are* anatomical systems, as opposed to sitting in one.

    Classification only. Asking with the containment closure as well catches
    everything inside a system too: the eyeball is part of the visual system,
    so a combined closure calls the eyeball a system and throws away the right
    answer for `cornea and retina`.
    """
    if not ids:
        return set()
    ancestors = ubergraph.ancestors(ids, via=(SUBCLASS_OF,), prefix="UBERON")
    return {
        term_id
        for term_id in ids
        if term_id in NOT_A_PLACE_ROOTS or (ancestors.get(term_id, set()) & NOT_A_PLACE_ROOTS)
    }


def _specialise_by_sex(
    result: TissueResult,
    text: str,
    index: LexicalIndex,
    ubergraph: Ubergraph,
    context: Context,
) -> TissueResult:
    """Narrow a sex-neutral term, but only on two independent signals agreeing.

    Anatomy and the sex field must both point the same way and either may veto.
    A string naming both sexes' organs is mixed; a library pooling both sexes
    cannot be specialised whatever the string says. The sex veto reads the raw
    text via the ``sex_mixed`` flag, because a pooled value maps to no term and
    an empty mapped field is indistinguishable from an absent one.
    """
    if context.sex_mixed or not context.sex_term:
        return result

    names_female = bool(_FEMALE_ANATOMY.search(text))
    names_male = bool(_MALE_ANATOMY.search(text))
    if names_female and names_male:
        result.match.flags.append("mixed_sex_anatomy")
        return result

    wanted = "female" if context.sex_term == "PATO:0000383" else "male"
    if (wanted == "female" and names_male) or (wanted == "male" and names_female):
        result.match.flags.append("sex_anatomy_disagrees_with_sex_field")
        result.match.needs_review = True
        return result

    current = result.match.term_id
    label = (result.match.term_name or "").lower()
    if wanted in label or "female" in label or "male" in label:
        return result  # already sex-specific

    descendants = ubergraph.descendants([current], prefix="UBERON").get(current, set())
    if not descendants:
        return result
    labels = ubergraph.labels(sorted(descendants))
    neutral = label
    siblings = [
        (term_id, name)
        for term_id, name in labels.items()
        if name and name.lower() == f"{wanted} {neutral}"
    ]
    if len(siblings) != 1:
        return result

    term_id, name = siblings[0]
    result.term_mature_id = result.term_mature_id or current
    result.term_mature_name = result.term_mature_name or result.match.term_name
    result.match.term_id, result.match.term_name = term_id, name
    result.match.rule = f"{result.match.rule}+sex_specialised"
    result.match.rationale += (
        f" Specialised to {term_id} ({name!r}): the sex field says {wanted}, the string names "
        f"no organ of the other sex, and {term_id} is an asserted descendant of {current}, so "
        "the narrowing provably keeps the same anatomy."
    )
    result.evidence["sex_specialisation"] = {"from": current, "to": term_id, "signal": wanted}
    return result


def _substitute_developmental(
    result: TissueResult, ubergraph: Ubergraph, context: Context
) -> TissueResult:
    """Swap a mature organ term for its precursor, but only when the age says so.

    Driven by data rather than by a blanket "is this embryonic": the mature
    term's own EHDAA2 window is asked whether the structure existed at the
    sample's age. Only when it says *no* is a precursor looked for, and only a
    precursor whose own window says *yes* is proposed. Germ layers are excluded
    -- they are upstream sources, never what a dissection yields.

    An open window returns "cannot say", which is not "no". EHDAA2 closes only
    1,058 of its 2,444 staged terms, and treating an open end as a refutation
    would substitute precursors for perfectly correct mature terms.
    """
    if not context.has_age or not result.match.assigned:
        return result

    current = result.match.term_id
    windows = ehdaa2.windows([current], ubergraph).get(current, [])
    if not windows:
        result.evidence["stage_check"] = "no EHDAA2 xref: no human window available"
        return result

    verdicts = [w.covers(context.dpf_start, context.dpf_end) for w in windows]
    result.evidence["stage_check"] = {
        "windows": [w.to_dict() for w in windows],
        "sample_dpf": [context.dpf_start, context.dpf_end],
        "covers": verdicts,
    }
    if any(v is not False for v in verdicts):
        return result  # exists, or cannot be ruled out -- keep the mature term

    from_uberon = ubergraph.develops_from([current]).get(current, [])
    from_ehdaa2 = ehdaa2.precursors([current], ubergraph).get(current, [])
    candidate_ids = {p["id"] for p in from_uberon if not p["germ_layer_prone"]}
    candidate_ids |= {p["uberon_id"] for p in from_ehdaa2 if p["uberon_id"]}
    candidate_ids.discard(current)

    viable = []
    if candidate_ids:
        precursor_windows = ehdaa2.windows(sorted(candidate_ids), ubergraph)
        labels = ubergraph.labels(sorted(candidate_ids))
        for term_id in sorted(candidate_ids):
            covering = [
                w for w in precursor_windows.get(term_id, [])
                if w.covers(context.dpf_start, context.dpf_end) is True
            ]
            if covering:
                viable.append(
                    {
                        "id": term_id,
                        "label": labels.get(term_id),
                        "window": covering[0].to_dict(),
                        "sources": sorted(
                            {"uberon" for p in from_uberon if p["id"] == term_id}
                            | {"ehdaa2" for p in from_ehdaa2 if p["uberon_id"] == term_id}
                        ),
                    }
                )

    result.match.needs_review = True
    result.match.flags.append("mature_term_predates_sample")
    if len(viable) != 1:
        result.match.candidates = [*result.match.candidates, *viable]
        result.match.rationale += (
            f" The sample is dated {context.dpf_start}-{context.dpf_end} dpf, before "
            f"{current} exists according to its EHDAA2 window. "
            + (
                f"{len(viable)} precursors also fit that age; none is assigned automatically."
                if viable
                else "No precursor with a covering window was found, so the mature term "
                "stands but is flagged."
            )
        )
        return result

    precursor = viable[0]
    result.term_mature_id = result.term_mature_id or current
    result.term_mature_name = result.term_mature_name or result.match.term_name
    result.match.term_id, result.match.term_name = precursor["id"], precursor["label"]
    result.match.match_type = "exact_developmental"
    result.match.rule = f"{result.match.rule}+developmental"
    result.match.rationale += (
        f" Substituted {precursor['id']} ({precursor['label']!r}): at "
        f"{context.dpf_start}-{context.dpf_end} dpf the mature term does not yet exist, "
        f"and this precursor's window does cover the sample "
        f"(source: {', '.join(precursor['sources'])}). The mature term is preserved."
    )
    result.evidence["developmental_substitution"] = precursor
    return result
