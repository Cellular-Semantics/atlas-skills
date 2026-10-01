"""String normalisation, and the two label-shape judgements that recur everywhere.

Nothing here talks to a service. It is all small, auditable and unit-tested,
because every rule in this module is a place where a plausible-looking
generalisation silently changes an answer.
"""

from __future__ import annotations

import re

# Dropped before comparing. Deliberately short: each word here is one that
# carries no anatomical content in a sample annotation.
STOPWORDS = frozenset({"of", "the", "a", "an", "region", "part", "portion", "zone"})

# Qualifiers that describe the sample rather than the anatomy. Stripping them
# turns "fetal liver tissue" into "liver", which is a term; leaving them in
# leaves it unmatchable.
NON_ANATOMICAL_QUALIFIERS = frozenset(
    {"fetal", "foetal", "embryonic", "adult", "human", "whole", "full", "tissue", "sample"}
)

# A *small* hand-written map, not a stemmer. A stemmer equates things that
# differ -- it will happily collapse "ureter" and "urethra" -- and the damage is
# invisible because the output is still a real term.
MORPHOLOGY = {
    "oesophagus": "esophagus",
    "oesophageal": "esophageal",
    "vertebrae": "vertebra",
    "ganglia": "ganglion",
    "cortices": "cortex",
    "haematopoietic": "hematopoietic",
    "foetal": "fetal",
    "colour": "color",
    "tumour": "tumor",
}

# Labels naming a *class of parts* rather than a place a sample came from.
# They are real terms and often the literally deepest common ancestor, and no
# curator would accept one as a sampled site. Matched as a prefix only: "zone of
# skin" is a grouping class, "subventricular zone" is anatomy.
GROUPING_PREFIXES = (
    "subdivision of ",
    "segment of ",
    "zone of ",
    "region of ",
    "portion of ",
    "part of ",
    "compound organ component",
    "anatomical cluster",
    "anatomical group",
)
GROUPING_SUFFIXES = (" element",)

# True of the parts, silent about the sample.
UNINFORMATIVE_UPPERS = frozenset(
    {
        "material entity",
        "anatomical entity",
        "anatomical structure",
        "anatomical system",
        "organ part",
        "organ component",
        "multicellular anatomical structure",
        "ectoderm-derived structure",
        "endoderm-derived structure",
        "mesoderm-derived structure",
        "embryonic structure",
        "developing anatomical structure",
        "tissue",
        "organ",
        "body part",
        # Reached constantly when parts span organ systems. They name a set of
        # things that function together, not a place a scalpel went.
        "disconnected anatomical group",
        "non-connected functional system",
        "anatomical group",
        "anatomical collection",
        "material anatomical entity",
        "organism subdivision",
        "multicellular organism",
        "whole organism",
        "anatomical conduit",
    }
)

_PUNCT = re.compile(r"[^\w\s-]+")
_SPACE = re.compile(r"\s+")


def is_grouping_class(label: str | None) -> bool:
    """A class of parts, not a place. Ranked below concrete anatomy at any depth.

    Two separate failures need this one predicate, which is why it is not buried
    in the common-ancestor code. `uterus, cervix, vagina` has `subdivision of
    oviduct` as a common ancestor tied on information content with `oviduct`;
    and `skin` matches `zone of skin` as a *unique exact synonym*, which the
    synonym rung would otherwise assign with no hesitation at all.
    """
    if not label:
        return False
    lowered = label.strip().lower()
    return lowered.startswith(GROUPING_PREFIXES) or lowered.endswith(GROUPING_SUFFIXES)


def is_uninformative(label: str | None) -> bool:
    return bool(label) and label.strip().lower() in UNINFORMATIVE_UPPERS


def normalise(text: str, *, drop_qualifiers: bool = True) -> str:
    """Lowercase, depunctuate, drop stopwords, apply the morphology map."""
    lowered = _PUNCT.sub(" ", text.lower())
    words = _SPACE.sub(" ", lowered).strip().split()
    kept = []
    for word in words:
        word = MORPHOLOGY.get(word, word)
        if word in STOPWORDS:
            continue
        if drop_qualifiers and word in NON_ANATOMICAL_QUALIFIERS:
            continue
        kept.append(word)
    return " ".join(kept)


def token_set(text: str, *, drop_qualifiers: bool = True) -> frozenset[str]:
    """The word set, for order-insensitive comparison. Same normalisation."""
    normalised = normalise(text, drop_qualifiers=drop_qualifiers)
    return frozenset(normalised.split()) if normalised else frozenset()


SPLIT_COMPOSITE = re.compile(r"\s*(?:;|,|/|\band\b|\+|\|)\s*")


def split_composite(text: str) -> list[str]:
    """Split a string naming several sites. Returns [text] if it names one."""
    parts = [p.strip() for p in SPLIT_COMPOSITE.split(text) if p and p.strip()]
    return parts if len(parts) > 1 else [text.strip()]
