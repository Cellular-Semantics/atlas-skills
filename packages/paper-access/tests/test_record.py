"""The record: what the schema pins, and what only a cross-check can."""

from __future__ import annotations

import pytest

from paper_access.errors import PaperAccessError
from paper_access.ids import Identifier
from paper_access.record import (
    AstaIndexing,
    Attempt,
    Availability,
    LocalSource,
    Metadata,
    check,
    cross_check,
    validate,
)


def jats_record() -> Availability:
    return Availability(
        input="10.1038/x",
        ids={"doi": Identifier.given("10.1038/x")},
        route="europepmc",
        local_source=LocalSource(
            kind="jats", path="source/paper.jats.xml", sha256="a" * 64, bytes=1234
        ),
        metadata=Metadata(source_api="europepmc", retrieved_at="2026-01-01T00:00:00+00:00",
                          title="A paper"),
        attempts=[Attempt("europepmc", "ok", "article XML for PMC1")],
        fetched_at="2026-01-01T00:00:00+00:00",
        attempted_at="2026-01-01T00:00:00+00:00",
    )


def test_a_good_record_validates_and_is_consistent():
    payload = jats_record().to_dict()
    validate(payload)
    assert cross_check(payload) == []


def test_round_trip():
    original = jats_record()
    assert Availability.from_dict(original.to_dict()).to_dict() == original.to_dict()


def test_a_record_from_a_future_schema_is_refused_rather_than_guessed_at():
    payload = jats_record().to_dict()
    payload["schema_version"] = 99
    with pytest.raises(PaperAccessError, match="schema_version"):
        Availability.from_dict(payload)


# -- route vs local_source ---------------------------------------------


def test_asta_route_with_no_bytes_is_legal():
    """The whole reason route and local_source are separate fields."""
    record = Availability(
        input="10.1038/x",
        ids={"doi": Identifier.given("10.1038/x")},
        route="asta",
        asta=AstaIndexing(band="full", probed_at="2026-01-01T00:00:00+00:00",
                          n_snippets=40, n_sections=12, n_ref_mentions=200),
        attempts=[Attempt("europepmc", "unavailable", "no record"),
                  Attempt("asta_probe", "unavailable", "40 snippets across 12 sections")],
        attempted_at="2026-01-01T00:00:00+00:00",
    )
    payload = record.to_dict()
    validate(payload)
    assert cross_check(payload) == []


def test_asta_route_with_a_thin_band_is_rejected():
    record = Availability(
        input="10.1038/x",
        ids={"doi": Identifier.given("10.1038/x")},
        route="asta",
        asta=AstaIndexing(band="abstract_only", probed_at="2026-01-01T00:00:00+00:00"),
        attempts=[Attempt("asta_probe", "unavailable", "abstract only")],
    )
    assert any("only 'full'" in p for p in cross_check(record.to_dict()))


def test_asta_route_with_bytes_on_disk_is_rejected():
    record = jats_record()
    record.route = "asta"
    record.asta = AstaIndexing(band="full", probed_at="2026-01-01T00:00:00+00:00")
    assert any("bytes are recorded on disk" in p for p in cross_check(record.to_dict()))


def test_a_retrieved_route_with_nothing_on_disk_is_rejected():
    record = jats_record()
    record.local_source = None
    problems = cross_check(record.to_dict())
    assert any("nothing is recorded on disk" in p for p in problems)


def test_route_none_needs_a_gap():
    record = Availability(
        input="10.1038/x",
        ids={"doi": Identifier.given("10.1038/x")},
        route="none",
        attempts=[Attempt("europepmc", "unavailable", "no record")],
    )
    assert any("no gap" in p for p in cross_check(record.to_dict()))


def test_route_none_cannot_have_a_successful_rung():
    record = Availability(
        input="10.1038/x",
        ids={"doi": Identifier.given("10.1038/x")},
        route="none",
        gap={"what": "x", "reason": "y"},
        attempts=[Attempt("europepmc", "ok", "got it")],
    )
    assert any("recorded as ok" in p for p in cross_check(record.to_dict()))


def test_the_probe_attempt_does_not_count_as_a_producing_rung():
    """asta_probe always runs and never produces bytes; it must not be
    mistaken for the rung that did."""
    record = jats_record()
    record.attempts.append(Attempt("asta_probe", "unavailable", "probed"))
    assert cross_check(record.to_dict()) == []


# -- text quality -------------------------------------------------------


def test_a_jats_source_carries_no_recovered_text():
    record = jats_record()
    record.local_source.text_file = "source/paper.txt"
    record.local_source.text_quality = {"n_segments": 1, "n_chars": 10}
    assert any("parsed directly" in p for p in cross_check(record.to_dict()))


def test_recovered_text_must_say_how_much_there_is():
    record = jats_record()
    record.local_source.kind = "pdf"
    record.local_source.path = "source/paper.pdf"
    record.local_source.text_file = "source/paper.txt"
    assert any("how much text" in p for p in cross_check(record.to_dict()))


# -- identifiers --------------------------------------------------------


def test_a_record_with_only_candidates_is_not_citable():
    record = Availability(
        input="Gopee 2024",
        ids={"doi": Identifier("10.1038/x", "europepmc", "2026-01-01T00:00:00+00:00", False)},
        route="none",
        gap={"what": "x", "reason": "y"},
        attempts=[],
    )
    assert any("candidate record" in p for p in cross_check(record.to_dict()))


def test_a_caller_supplied_identifier_has_no_lookup_time():
    record = jats_record()
    payload = record.to_dict()
    payload["ids"]["doi"]["at"] = "2026-01-01T00:00:00+00:00"
    assert any("carries a lookup time" in p for p in cross_check(payload))


def test_primary_id_prefers_a_doi_and_ignores_candidates():
    record = Availability(
        input="x",
        ids={
            "pmid": Identifier.given("123"),
            "doi": Identifier("10.1038/x", "europepmc", "2026-01-01T00:00:00+00:00", False),
        },
    )
    assert record.primary_id == ("pmid", "123")


def test_a_record_with_no_confirmed_identifier_cannot_be_filed():
    record = Availability(
        input="Gopee 2024",
        ids={"doi": Identifier("10.1038/x", "europepmc", None, False)},
    )
    with pytest.raises(PaperAccessError, match="candidate"):
        _ = record.primary_id


# -- open access --------------------------------------------------------


def test_a_used_location_must_match_the_route():
    record = jats_record()
    record.oa_candidates = [{"url": "http://x", "used": True}]
    assert any("marked used but the route" in p for p in cross_check(record.to_dict()))


# -- asta block ---------------------------------------------------------


def test_the_missing_figure_legends_are_always_on_the_record():
    band = AstaIndexing(band="full", probed_at="2026-01-01T00:00:00+00:00")
    assert band.to_dict()["has_figure_legends"] is False


def test_skipped_is_not_a_measurement():
    assert not AstaIndexing(band="skipped", probed_at="x").measured
    assert AstaIndexing(band="unindexed", probed_at="x").measured


def test_check_reports_a_schema_failure_rather_than_raising():
    assert check({"nonsense": True})
