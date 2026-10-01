"""The rule ladder, and the refusals that matter more than the matches."""

from conftest import make_index
from ontomap.ladder import resolve

# A miniature UBERON, containing exactly the shapes that caused trouble.
INDEX = make_index(
    "UBERON",
    [
        ("UBERON:0002107", "liver", "label"),
        ("UBERON:0002097", "skin of body", "label"),
        ("UBERON:0002097", "skin", "related"),
        ("UBERON:0000014", "zone of skin", "label"),
        ("UBERON:0000014", "skin", "exact"),
        ("UBERON:0001003", "skin epidermis", "label"),
        ("UBERON:0001003", "skin", "broad"),
        ("UBERON:0002370", "thymus", "label"),
        ("UBERON:0000955", "brain", "label"),
        ("UBERON:0000955", "encephalon", "exact"),
        ("UBERON:0002048", "lung", "label"),
        ("UBERON:0001004", "respiratory system", "label"),
        ("UBERON:0001004", "lung", "broad"),
    ],
)


def test_exact_label():
    match = resolve("liver", INDEX)
    assert (match.rule, match.term_id) == ("exact_label", "UBERON:0002107")


def test_exact_synonym_assigns_when_it_is_the_only_one():
    match = resolve("encephalon", INDEX)
    assert (match.rule, match.term_id) == ("exact_synonym", "UBERON:0000955")


def test_skin_does_not_become_zone_of_skin():
    """The unique-exact-synonym rung is not safe on its own.

    "skin" is a *unique exact synonym* of `zone of skin`, a grouping class,
    while `skin of body` -- the term intended -- carries it only as a related
    synonym. Uniqueness alone assigns the wrong term with no hesitation, so
    grouping classes are removed before the rung is applied and the string
    falls through to judgement with every candidate attached.
    """
    match = resolve("skin", INDEX)
    assert match.term_id is None
    assert match.rule == "candidates_only"
    assert "UBERON:0002097" in {c["id"] for c in match.candidates}


def test_normalised_label_strips_sample_qualifiers():
    match = resolve("fetal liver tissue", INDEX)
    assert (match.rule, match.term_id) == ("normalised_label", "UBERON:0002107")


def test_nothing_matched_means_no_id():
    for text in ("upper reproductive tract", "mid vertebrae", "internal organs", "embryo head"):
        match = resolve(text, INDEX)
        assert match.term_id is None, f"{text!r} must not resolve to anything"
        assert match.needs_review


def test_broad_and_related_synonyms_never_assign():
    # "lung" is a broad synonym of respiratory system here, and also a label.
    # The label must win and the broad synonym must not create an ambiguity.
    match = resolve("lung", INDEX)
    assert match.term_id == "UBERON:0002048"


def test_placeholders_are_not_anatomy():
    match = resolve("n/a", INDEX, placeholders=frozenset({"n/a"}))
    assert match.rule == "placeholder"
