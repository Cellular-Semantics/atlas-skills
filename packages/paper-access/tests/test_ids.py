"""Identifier normalisation, and the line between exact and vague input."""

from __future__ import annotations

import pytest

from paper_access.errors import PaperAccessError
from paper_access.ids import (
    Identifier,
    find_ids,
    looks_exact,
    normalise_doi,
    normalise_pmcid,
    normalise_pmid,
    parse_id,
    slug,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("10.1038/s41586-023-06812-z", "10.1038/s41586-023-06812-z"),
        ("https://doi.org/10.1038/S41586-023-06812-Z", "10.1038/s41586-023-06812-z"),
        ("doi:10.1038/s41586-023-06812-z", "10.1038/s41586-023-06812-z"),
        ("  10.1038/s41586-023-06812-z.  ", "10.1038/s41586-023-06812-z"),
        ("10.1038/s41586-023-06812-z)", "10.1038/s41586-023-06812-z"),
    ],
)
def test_doi_normalisation(raw, expected):
    assert normalise_doi(raw) == expected


def test_doi_case_is_folded_so_one_paper_is_one_directory():
    """A publisher shouting its suffix must not create a second copy."""
    assert normalise_doi("10.1038/S41586") == normalise_doi("10.1038/s41586")


def test_a_doi_keeping_internal_punctuation():
    """Only *trailing* punctuation is stripped; all of it is legal inside."""
    assert normalise_doi("10.1371/journal.pone.0012345") == "10.1371/journal.pone.0012345"


@pytest.mark.parametrize("raw", ["not a doi", "10.x/y", "", "PMC123"])
def test_doi_rejects_what_is_not_one(raw):
    with pytest.raises(PaperAccessError):
        normalise_doi(raw)


def test_pmid_and_pmcid():
    assert normalise_pmid("PMID: 38168772") == "38168772"
    assert normalise_pmid("0038168772") == "38168772"
    assert normalise_pmcid("pmc10769438") == "PMC10769438"
    assert normalise_pmcid("10769438") == "PMC10769438"
    assert normalise_pmcid("PMCID:PMC10769438") == "PMC10769438"


@pytest.mark.parametrize(
    ("raw", "kind"),
    [
        ("10.1038/x", "doi"),
        ("https://doi.org/10.1038/x", "doi"),
        ("PMC123456", "pmcid"),
        ("PMID:38168772", "pmid"),
        ("38168772", "pmid"),
    ],
)
def test_parse_id_recognises_the_exact_forms(raw, kind):
    assert parse_id(raw)[0] == kind


@pytest.mark.parametrize(
    "raw",
    [
        "Gopee 2024 prenatal skin atlas",
        "Yao et al., Nature 2023",
        "a whole mouse brain atlas",
    ],
)
def test_free_text_is_not_an_exact_identifier(raw):
    """The whole two-phase rule rests on this boundary."""
    assert not looks_exact(raw)
    with pytest.raises(PaperAccessError, match="resolve"):
        parse_id(raw)


def test_identifier_provenance_is_part_of_the_value():
    given = Identifier.given("10.1038/x")
    assert given.source == "input" and given.at is None and given.confirmed
    returned = Identifier.returned("PMC1", "europepmc")
    assert returned.source == "europepmc" and returned.at


def test_an_identifier_cannot_claim_an_unknown_source():
    """There is deliberately no 'inferred'."""
    with pytest.raises(PaperAccessError, match="not a known identifier source"):
        Identifier(value="10.1038/x", source="inferred")


def test_round_trip_through_a_dict():
    original = Identifier("10.1038/x", "crossref", "2026-01-01T00:00:00+00:00", False)
    assert Identifier.from_dict(original.to_dict()) == original


def test_find_ids_is_greedy_on_dois_and_careful_with_numbers():
    text = (
        "As shown previously (10.1038/s41586-023-06812-z) and in PMC10769438, "
        "see also PMID: 38168772. In 2023 we found 12345 cells."
    )
    found = find_ids(text)
    assert found["doi"] == {"10.1038/s41586-023-06812-z"}
    assert found["pmcid"] == {"PMC10769438"}
    assert found["pmid"] == {"38168772"}
    # The bare cell count is a number, not a PMID.
    assert "12345" not in found["pmid"]


def test_slug_keeps_a_doi_legible():
    assert slug("doi", "10.1038/s41586-023-06812-z") == "10.1038_s41586-023-06812-z"
    assert slug("pmcid", "PMC123") == "pmcid_PMC123"


def test_slug_tames_an_awkward_doi():
    assert "/" not in slug("doi", "10.1234/a b<c>d")
