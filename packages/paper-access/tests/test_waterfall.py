"""The waterfall end to end, against a mocked network.

Everything here runs offline. The rungs are exercised through a MockTransport
so the ordering, the record that comes out, and the negative cache are all
tested against the shapes the real services return.
"""

from __future__ import annotations

import json

import httpx
import pytest

from paper_access import store, waterfall
from paper_access.errors import PaperAccessError
from paper_access.ids import Identifier
from paper_access.record import Attempt, Availability

DOI = "10.1038/s41586-023-06812-z"

JATS = b"""<?xml version="1.0"?>
<article xmlns:xlink="http://www.w3.org/1999/xlink">
  <front><article-meta>
    <article-title>A high-resolution transcriptomic atlas</article-title>
  </article-meta></front>
  <body><sec><p>Text.</p></sec></body>
</article>
"""

EPMC_HIT = {
    "resultList": {
        "result": [
            {
                "doi": DOI,
                "pmid": "38168772",
                "pmcid": "PMC10769438",
                "title": "A high-resolution transcriptomic atlas.",
                "pubYear": "2023",
                "isOpenAccess": "Y",
                "journalInfo": {"journal": {"title": "Nature"}},
                "authorList": {"author": [{"fullName": "Yao Z"}, {"fullName": "Smith J"}]},
            }
        ]
    }
}

EPMC_MISS = {"resultList": {"result": []}}


#: The real class, captured before any test swaps it out.
_REAL_CLIENT = httpx.Client


class Net:
    """A scriptable stand-in for every service the rungs call."""

    def __init__(self, **kwargs):
        self.epmc_search = kwargs.get("epmc_search", EPMC_MISS)
        self.fulltext = kwargs.get("fulltext")
        self.preprint = kwargs.get("preprint", {"messages": [{"status": "no posts found"}]})
        self.unpaywall = kwargs.get("unpaywall", {"is_oa": False})
        self.asta = kwargs.get("asta", {"data": []})
        self.seen: list[str] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        self.seen.append(url)
        if "europepmc" in url and "/search" in url:
            return httpx.Response(200, json=self.epmc_search)
        if "fullTextXML" in url:
            if self.fulltext is None:
                return httpx.Response(404, text="not open")
            return httpx.Response(200, content=self.fulltext)
        if "biorxiv.org/details" in url:
            return httpx.Response(200, json=self.preprint)
        if "unpaywall" in url:
            return httpx.Response(200, json=self.unpaywall)
        if "snippet/search" in url:
            return httpx.Response(200, json=self.asta)
        return httpx.Response(404, text=f"unexpected {url}")

    def client(self, **_kwargs):
        return _REAL_CLIENT(transport=httpx.MockTransport(self.handler))


@pytest.fixture
def net(monkeypatch):
    """Install a scriptable network for the whole waterfall."""
    holder: dict[str, Net] = {}

    def install(**kwargs) -> Net:
        instance = Net(**kwargs)
        holder["net"] = instance
        monkeypatch.setattr(httpx, "Client", instance.client)
        return instance

    return install


@pytest.fixture(autouse=True)
def _no_ambient_config(monkeypatch):
    monkeypatch.setenv("ASTA_API_KEY", "test-key")
    monkeypatch.setenv("PAPER_ACCESS_CONTACT_EMAIL", "test@example.org")


def asta_full():
    return {
        "data": [
            {
                "snippet": {
                    "text": "y" * 1000,
                    "section": f"S{i % 12}",
                    "annotations": {"refMentions": [{"matchedPaperCorpusId": 1}] * 5},
                },
                "paper": {"corpusId": 266222435},
            }
            for i in range(20)
        ]
    }


# -- the happy path -----------------------------------------------------


def test_jats_comes_first_and_the_probe_still_runs(net, tmp_path):
    scripted = net(epmc_search=EPMC_HIT, fulltext=JATS, asta=asta_full())
    record = waterfall.fetch(DOI, tmp_path)

    assert record.route == "europepmc"
    assert record.local_source.kind == "jats"
    assert (tmp_path / "10.1038_s41586-023-06812-z" / "source" / "paper.jats.xml").is_file()

    # The probe runs even though JATS already served the paper: the band is a
    # fact about the corpus worth having on every record.
    assert record.asta is not None and record.asta.band == "full"
    assert any("snippet/search" in url for url in scripted.seen)


def test_the_probe_never_claims_the_route_when_a_rung_produced_bytes(net, tmp_path):
    net(epmc_search=EPMC_HIT, fulltext=JATS, asta=asta_full())
    record = waterfall.fetch(DOI, tmp_path)
    assert record.route == "europepmc"


def test_identifiers_an_api_returned_carry_its_name(net, tmp_path):
    net(epmc_search=EPMC_HIT, fulltext=JATS)
    record = waterfall.fetch(DOI, tmp_path)

    assert record.ids["doi"].source == "input"
    assert record.ids["pmcid"].value == "PMC10769438"
    assert record.ids["pmcid"].source == "europepmc"
    assert record.ids["pmcid"].at


def test_metadata_is_stamped_with_the_api_that_produced_it(net, tmp_path):
    net(epmc_search=EPMC_HIT, fulltext=JATS)
    record = waterfall.fetch(DOI, tmp_path)
    assert record.metadata.source_api == "europepmc"
    assert record.metadata.title == "A high-resolution transcriptomic atlas"
    assert record.metadata.authors == ["Yao Z", "Smith J"]


# -- falling through ----------------------------------------------------


def test_asta_serves_a_paper_no_rung_could_get(net, tmp_path):
    net(asta=asta_full())
    record = waterfall.fetch(DOI, tmp_path)

    assert record.route == "asta"
    assert record.local_source is None
    assert record.asta.band == "full"
    assert record.gap is None
    # And the record says out loud what an ASTA-only paper is missing.
    assert record.to_dict()["asta"]["has_figure_legends"] is False


def test_the_probe_attempt_says_ok_only_when_the_index_can_serve(net, tmp_path):
    """'ok' on an asta_probe means the index holds the paper, not that the
    file came from there — so it must not appear for a band that cannot
    serve, and must appear for one that can."""
    net(asta=asta_full())
    record = waterfall.fetch(DOI, tmp_path)
    probe = next(a for a in record.attempts if a.route == "asta_probe")
    assert probe.outcome == "ok"
    assert record.route == "asta"


def test_the_probe_attempt_is_unavailable_for_a_thin_band(net, tmp_path):
    net(asta={"data": [{"snippet": {"text": "abstract"}}]})
    record = waterfall.fetch(DOI, tmp_path)
    probe = next(a for a in record.attempts if a.route == "asta_probe")
    assert probe.outcome == "unavailable"


def test_a_servable_band_does_not_steal_the_route_from_a_real_rung(net, tmp_path):
    """The probe records 'ok' and the paper still came from Europe PMC."""
    net(epmc_search=EPMC_HIT, fulltext=JATS, asta=asta_full())
    record = waterfall.fetch(DOI, tmp_path)
    assert record.route == "europepmc"
    assert next(a for a in record.attempts if a.route == "asta_probe").outcome == "ok"


def test_the_probe_attempt_is_skipped_without_a_key(net, tmp_path, monkeypatch):
    monkeypatch.delenv("ASTA_API_KEY", raising=False)
    net()
    record = waterfall.fetch(DOI, tmp_path)
    assert next(a for a in record.attempts if a.route == "asta_probe").outcome == "skipped"


def test_a_thin_asta_band_does_not_serve(net, tmp_path):
    net(asta={"data": [{"snippet": {"text": "abstract"}}]})
    record = waterfall.fetch(DOI, tmp_path)
    assert record.route == "none"
    assert record.asta.band == "abstract_only"
    assert record.gap


def test_nothing_anywhere_produces_an_actionable_gap(net, tmp_path):
    net()
    record = waterfall.fetch(DOI, tmp_path)
    assert record.route == "none"
    assert "doi.org" in record.gap["action"]
    assert "adopt" in record.gap["action"]
    assert "europepmc unavailable" in record.gap["reason"]


def test_an_open_access_landing_page_is_where_the_gap_sends_you(net, tmp_path):
    net(unpaywall={
        "is_oa": True,
        "best_oa_location": {"url": "https://repo.example/item/1", "host_type": "repository"},
    })
    record = waterfall.fetch(DOI, tmp_path)
    assert record.route == "none"
    assert "https://repo.example/item/1" in record.gap["action"]
    assert record.oa_candidates[0]["host_type"] == "repository"


def test_a_missing_asta_key_is_skipped_not_unindexed(net, tmp_path, monkeypatch):
    monkeypatch.delenv("ASTA_API_KEY", raising=False)
    net()
    record = waterfall.fetch(DOI, tmp_path)
    assert record.asta.band == "skipped"
    assert not record.asta.measured


# -- the negative cache -------------------------------------------------


def test_an_unreachable_paper_is_not_re_requested(net, tmp_path):
    scripted = net()
    waterfall.fetch(DOI, tmp_path)
    before = len(scripted.seen)
    waterfall.fetch(DOI, tmp_path)
    assert len(scripted.seen) == before


def test_retry_overrides_the_negative_cache(net, tmp_path):
    scripted = net()
    waterfall.fetch(DOI, tmp_path)
    before = len(scripted.seen)
    waterfall.fetch(DOI, tmp_path, retry=True)
    assert len(scripted.seen) > before


def test_an_outage_does_not_settle_anything(net, tmp_path):
    """A rung that broke has established nothing about the paper. If that
    counted as settled, an afternoon's downtime would mark a retrievable paper
    permanently unreachable."""
    record = Availability(
        input=DOI,
        ids={"doi": Identifier.given(DOI)},
        route="none",
        attempts=[Attempt("europepmc", "failed", "connection reset")],
    )
    assert not waterfall.settled(record)

    record.attempts = [Attempt("europepmc", "unavailable", "no record")]
    assert waterfall.settled(record)


def test_a_missing_dependency_does_not_settle_anything():
    record = Availability(
        input=DOI,
        ids={"doi": Identifier.given(DOI)},
        attempts=[Attempt("preprint_server", "skipped", "curl_cffi is not installed")],
    )
    assert not waterfall.settled(record)


def test_a_paper_already_here_is_not_re_fetched(net, tmp_path):
    scripted = net(epmc_search=EPMC_HIT, fulltext=JATS)
    waterfall.fetch(DOI, tmp_path)
    before = len(scripted.seen)
    again = waterfall.fetch(DOI, tmp_path)
    assert len(scripted.seen) == before
    assert again.route == "europepmc"


def test_bytes_that_changed_underneath_the_record_are_re_fetched(net, tmp_path):
    scripted = net(epmc_search=EPMC_HIT, fulltext=JATS)
    waterfall.fetch(DOI, tmp_path)
    source = tmp_path / "10.1038_s41586-023-06812-z" / "source" / "paper.jats.xml"
    source.write_bytes(JATS + b"<!-- edited -->")
    before = len(scripted.seen)
    waterfall.fetch(DOI, tmp_path)
    assert len(scripted.seen) > before


# -- input discipline ---------------------------------------------------


def test_fetch_refuses_anything_that_is_not_an_exact_identifier(tmp_path):
    with pytest.raises(PaperAccessError, match="resolve"):
        waterfall.fetch("Gopee 2024 prenatal skin", tmp_path)


def test_resolve_passes_an_exact_identifier_straight_through():
    assert waterfall.resolve("  10.1038/X  ") == {
        "input": "  10.1038/X  ",
        "status": "confirmed",
        "kind": "doi",
        "value": "10.1038/x",
    }


def test_resolve_returns_candidates_for_free_text_and_confirms_nothing(net):
    net(epmc_search=EPMC_HIT)
    result = waterfall.resolve("Yao 2023 whole mouse brain atlas")
    assert result["status"] == "candidates"
    assert result["candidates"][0]["doi"] == DOI
    assert result["candidates"][0]["title"] == "A high-resolution transcriptomic atlas"
    # Crucially: no confirmed identifier anywhere in the answer.
    assert "value" not in result


def test_resolve_says_so_when_it_finds_nothing(net):
    net()
    assert waterfall.resolve("nonsense query")["status"] == "unresolved"


# -- adopting a supplied file -------------------------------------------


def test_adopt_takes_in_article_xml(tmp_path):
    supplied = tmp_path / "drop" / "paper.xml"
    supplied.parent.mkdir()
    supplied.write_bytes(JATS)
    record = waterfall.adopt(DOI, tmp_path / "store", supplied)
    assert record.route == "manual"
    assert record.local_source.kind == "jats"


def test_adopt_rejects_a_saved_landing_page(tmp_path):
    supplied = tmp_path / "paper.xml"
    supplied.write_bytes(b"<html><body>Access denied</body></html>")
    with pytest.raises(PaperAccessError, match="landing page"):
        waterfall.adopt(DOI, tmp_path / "store", supplied)


def test_adopt_rejects_a_pdf_that_is_not_one(tmp_path):
    supplied = tmp_path / "paper.pdf"
    supplied.write_bytes(b"<html>Error 403</html>")
    with pytest.raises(PaperAccessError, match="%PDF"):
        waterfall.adopt(DOI, tmp_path / "store", supplied)


def test_adopt_keeps_what_an_earlier_probe_learnt(net, tmp_path):
    net(asta=asta_full())
    waterfall.fetch(DOI, tmp_path)
    supplied = tmp_path / "paper.xml"
    supplied.write_bytes(JATS)
    record = waterfall.adopt(DOI, tmp_path, supplied)
    assert record.asta is not None and record.asta.band == "full"
    assert record.route == "manual"


# -- notes --------------------------------------------------------------


def test_note_is_the_only_field_a_person_writes(net, tmp_path):
    net(epmc_search=EPMC_HIT, fulltext=JATS)
    waterfall.fetch(DOI, tmp_path)
    record = waterfall.note(DOI, tmp_path, "this is the accepted manuscript")
    assert record.notes == "this is the accepted manuscript"
    reread = store.read(tmp_path, DOI)
    assert reread.notes == "this is the accepted manuscript"
    # And it did not disturb anything that came from an API.
    assert reread.metadata.source_api == "europepmc"


def test_note_needs_a_record_to_attach_to(tmp_path):
    with pytest.raises(PaperAccessError, match="no record"):
        waterfall.note(DOI, tmp_path, "x")


# -- drop zones ---------------------------------------------------------


def test_candidates_reports_the_declared_identifier_and_title(tmp_path):
    (tmp_path / "media-1.xml").write_bytes(JATS)
    (tmp_path / "notes.txt").write_text("not a paper")
    found = waterfall.candidates(tmp_path)
    assert len(found) == 1
    assert found[0]["title"] == "A high-resolution transcriptomic atlas"
    assert found[0]["kind"] == "jats"


def test_a_supplement_with_no_doi_is_visibly_missing_one(tmp_path):
    """The absence of a DOI is the strongest signal a drop zone offers."""
    (tmp_path / "media-2.xml").write_bytes(
        b'<article><front><article-meta><article-title>'
        b'GarciaAlonso 2026 Pediatric</article-title></article-meta></front></article>'
    )
    found = waterfall.candidates(tmp_path)
    assert "doi" not in found[0]
    assert found[0]["title"] == "GarciaAlonso 2026 Pediatric"


# -- reporting ----------------------------------------------------------


def test_report_says_route_kind_and_band(net, tmp_path):
    net(epmc_search=EPMC_HIT, fulltext=JATS, asta=asta_full())
    waterfall.fetch(DOI, tmp_path)
    rows = waterfall.report(tmp_path)
    assert rows[0]["route"] == "europepmc"
    assert rows[0]["kind"] == "jats"
    assert rows[0]["asta_band"] == "full"


def test_verify_notices_an_identifier_that_resolves_elsewhere(net, tmp_path):
    net(epmc_search=EPMC_HIT, fulltext=JATS)
    waterfall.fetch(DOI, tmp_path)

    path = tmp_path / "10.1038_s41586-023-06812-z" / "availability.json"
    payload = json.loads(path.read_text())
    payload["metadata"]["title"] = "An entirely different paper about yeast"
    path.write_text(json.dumps(payload))

    results = waterfall.verify(tmp_path)
    assert results[0]["status"] == "mismatch"


def test_verify_passes_a_record_that_still_agrees(net, tmp_path):
    net(epmc_search=EPMC_HIT, fulltext=JATS)
    waterfall.fetch(DOI, tmp_path)
    assert waterfall.verify(tmp_path)[0]["status"] == "ok"
