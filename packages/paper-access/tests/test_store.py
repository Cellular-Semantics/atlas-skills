"""The store: where things go, and what it refuses to write."""

from __future__ import annotations

import json

import pytest

from paper_access import store
from paper_access.errors import PaperAccessError
from paper_access.ids import Identifier
from paper_access.record import Attempt, Availability, LocalSource, Metadata

DOI = "10.1038/s41586-023-06812-z"


def good() -> Availability:
    return Availability(
        input=DOI,
        ids={
            "doi": Identifier.given(DOI),
            "pmcid": Identifier.returned("PMC10769438", "europepmc"),
        },
        route="europepmc",
        local_source=LocalSource(
            kind="jats", path="source/paper.jats.xml", sha256="a" * 64, bytes=10
        ),
        metadata=Metadata(source_api="europepmc", retrieved_at="2026-01-01T00:00:00+00:00"),
        attempts=[Attempt("europepmc", "ok")],
        fetched_at="2026-01-01T00:00:00+00:00",
    )


def test_a_paper_is_filed_under_its_doi(tmp_path):
    path = store.write(tmp_path, good())
    assert path.parent.name == "10.1038_s41586-023-06812-z"
    assert path.name == "availability.json"


def test_a_paper_is_found_by_any_identifier_it_carries(tmp_path):
    """Asking for a paper by PMCID when it was filed by DOI must not fetch it
    a second time."""
    store.write(tmp_path, good())
    assert store.read(tmp_path, DOI) is not None
    assert store.read(tmp_path, "PMC10769438") is not None
    assert store.read(tmp_path, "PMC999999") is None


def test_an_inconsistent_record_is_never_left_on_disk(tmp_path):
    record = good()
    record.local_source = None  # claims a route with nothing stored
    with pytest.raises(PaperAccessError, match="not self-consistent"):
        store.write(tmp_path, record)
    assert not list(tmp_path.glob("*/availability.json"))


def test_a_record_that_does_not_match_the_schema_is_never_written(tmp_path):
    record = good()
    record.route = "telepathy"
    with pytest.raises(PaperAccessError):
        store.write(tmp_path, record)
    assert not list(tmp_path.glob("*/availability.json"))


def test_bytes_go_beside_the_record_and_paths_are_relative(tmp_path):
    record = good()
    store.write(tmp_path, record)
    store.store_bytes(tmp_path, record, "jats", b"<article/>")
    reread = json.loads((tmp_path / "10.1038_s41586-023-06812-z" / "availability.json").read_text())
    assert reread["local_source"]["path"] == "source/paper.jats.xml"
    assert not reread["local_source"]["path"].startswith("/")


def test_intact_notices_bytes_that_changed(tmp_path):
    record = good()
    body = b"<article/>"
    record.local_source.sha256 = store.digest(body)
    record.local_source.bytes = len(body)
    store.write(tmp_path, record)
    store.store_bytes(tmp_path, record, "jats", body)
    assert store.intact(tmp_path, record)

    store.store_bytes(tmp_path, record, "jats", body + b"<!-- -->")
    assert not store.intact(tmp_path, record)


def test_intact_is_false_when_the_file_went_away(tmp_path):
    record = good()
    store.write(tmp_path, record)
    assert not store.intact(tmp_path, record)


def test_read_all_on_an_empty_or_absent_store(tmp_path):
    assert store.read_all(tmp_path / "nope") == []
    assert store.read_all(tmp_path) == []


def test_a_corrupt_record_says_which_file(tmp_path):
    directory = tmp_path / "10.1038_x"
    directory.mkdir()
    (directory / "availability.json").write_text("{not json")
    with pytest.raises(PaperAccessError, match="cannot read"):
        store.read_all(tmp_path)


# -- identifier precedence ---------------------------------------------


def test_a_confirmed_identifier_is_not_replaced_by_a_candidate():
    record = Availability(input="x", ids={"doi": Identifier.given(DOI)})
    store.add_id(record, "doi", Identifier("10.9999/wrong", "europepmc", None, False))
    assert record.ids["doi"].value == DOI


def test_what_the_caller_supplied_beats_what_an_api_guessed():
    record = Availability(input="x", ids={"doi": Identifier.given(DOI)})
    store.add_id(record, "doi", Identifier.returned("10.9999/other", "europepmc"))
    assert record.ids["doi"].source == "input"


def test_an_api_identifier_fills_a_gap():
    record = Availability(input="x", ids={})
    store.add_id(record, "pmcid", Identifier.returned("PMC1", "europepmc"))
    assert record.ids["pmcid"].value == "PMC1"
