"""Checking a document's citations against the store."""

from __future__ import annotations

import pytest

from paper_access import refs, store
from paper_access.errors import PaperAccessError
from paper_access.ids import Identifier
from paper_access.record import Attempt, Availability, LocalSource, Metadata

DOI = "10.1038/s41586-023-06812-z"
OTHER = "10.1016/j.cell.2021.04.048"


@pytest.fixture
def populated(tmp_path):
    record = Availability(
        input=DOI,
        ids={
            "doi": Identifier.given(DOI),
            "pmcid": Identifier.returned("PMC10769438", "europepmc"),
        },
        route="europepmc",
        local_source=LocalSource(
            kind="jats", path="source/paper.jats.xml", sha256="a" * 64, bytes=1
        ),
        metadata=Metadata(source_api="europepmc", retrieved_at="2026-01-01T00:00:00+00:00"),
        attempts=[Attempt("europepmc", "ok")],
        fetched_at="2026-01-01T00:00:00+00:00",
    )
    store.write(tmp_path, record)
    return tmp_path


def test_a_document_citing_only_what_is_in_the_store_passes(populated, tmp_path):
    doc = tmp_path / "report.md"
    doc.write_text(f"The atlas paper ({DOI}, PMC10769438) reports 5,322 clusters.")
    assert refs.check_document(doc, populated) == []


def test_an_identifier_the_store_does_not_hold_is_reported(populated, tmp_path):
    doc = tmp_path / "report.md"
    doc.write_text(f"Also see {OTHER}, which we definitely read.")
    problems = refs.check_document(doc, populated)
    assert problems == [{"kind": "doi", "value": OTHER}]


def test_the_check_is_one_directional(populated, tmp_path):
    """A report covering a subset of the corpus is the normal case, so papers
    the document does not cite are never complained about."""
    doc = tmp_path / "report.md"
    doc.write_text("No identifiers at all in this one.")
    assert refs.check_document(doc, populated) == []


def test_a_candidate_in_the_store_counts_as_known(tmp_path):
    """A document describing a question a person is being asked is not making
    a claim."""
    record = Availability(
        input="Gopee 2024",
        ids={
            "doi": Identifier.given(DOI),
            "pmid": Identifier("38168772", "europepmc", "2026-01-01T00:00:00+00:00", False),
        },
        route="none",
        gap={"what": "x", "reason": "y"},
        attempts=[Attempt("europepmc", "unavailable")],
    )
    store.write(tmp_path, record)
    doc = tmp_path / "report.md"
    doc.write_text("Candidate PMID: 38168772 awaiting confirmation.")
    assert refs.check_document(doc, tmp_path) == []


def test_a_missing_document_says_so(tmp_path):
    with pytest.raises(PaperAccessError, match="no such file"):
        refs.check_document(tmp_path / "nope.md", tmp_path)


def test_the_message_tells_you_what_to_do_and_what_not_to(populated, tmp_path):
    doc = tmp_path / "report.md"
    doc.write_text(f"see {OTHER}")
    problems = refs.check_document(doc, populated)
    message = refs.describe(problems, doc, populated)
    assert OTHER in message
    assert "paper-access fetch" in message
    assert "from memory" in message


def test_an_empty_store_makes_every_citation_unknown(tmp_path):
    doc = tmp_path / "report.md"
    doc.write_text(f"see {DOI}")
    assert refs.check_document(doc, tmp_path / "empty") == [{"kind": "doi", "value": DOI}]
