"""The index-depth probe: band classification at each calibration boundary.

The bands are pinned against the measured table in the module docstring. The
gaps between the observed bands are wide, so these tests are about the
*decision rule* holding, not about the exact thresholds being right.
"""

from __future__ import annotations

import httpx
import pytest

from paper_access.asta import (
    PARTIAL_CHARS,
    classify_rows,
    count_signals,
    probe,
    search_snippets,
)
from paper_access.errors import PaperAccessError


def row(text: str = "x", section: str | None = None, refs: int = 0, corpus: int | None = None):
    snippet = {
        "text": text,
        "section": section,
        "annotations": {"refMentions": [{"matchedPaperCorpusId": 1}] * refs},
    }
    out = {"snippet": snippet}
    if corpus is not None:
        out["paper"] = {"corpusId": corpus}
    return out


def full_rows(n: int = 20):
    """A body: many chunks, many sections, a bibliography."""
    return [
        row("y" * 1000, section=f"Section {i % 12}", refs=5, corpus=266222435)
        for i in range(n)
    ]


# -- the bands ----------------------------------------------------------


def test_nothing_indexed():
    report = classify_rows([])
    assert report.band == "unindexed"
    assert "0 snippets" in report.reason


def test_yao_2023_is_abstract_only_despite_every_surface_signal():
    """The worked example: open access, in PMC, 118 graph references, and
    three chunks of title and abstract in the snippet index."""
    rows = [row("t" * 400, corpus=266222435) for _ in range(3)]
    report = classify_rows(rows)
    assert report.band == "abstract_only"
    assert report.corpus_id == "CorpusId:266222435"
    assert report.n_sections == 0 and report.n_ref_mentions == 0


def test_a_body_with_sections_and_references_is_full():
    report = classify_rows(full_rows())
    assert report.band == "full"
    assert report.servable


def test_too_few_snippets_is_partial_however_rich():
    report = classify_rows(full_rows(5))
    assert report.band == "partial"
    assert not report.servable


def test_too_little_text_is_partial():
    rows = [row("z" * 10, section=f"S{i}", refs=5) for i in range(20)]
    report = classify_rows(rows)
    assert report.band == "partial"
    assert report.n_chars < PARTIAL_CHARS


def test_sections_without_a_bibliography_is_partial_not_full():
    """The two signals are orthogonal: only a body carries references."""
    rows = [row("y" * 1000, section=f"S{i % 12}") for i in range(20)]
    assert classify_rows(rows).band == "partial"


def test_a_null_section_name_is_the_abstract_signal():
    """Section is null for title/abstract pseudo-chunks, and that absence is
    exactly what separates a body from an abstract."""
    _, sections, _, _ = count_signals([row(section=None), row(section="")])
    assert sections == set()


# -- the transport ------------------------------------------------------


def client_returning(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_probe_without_a_key_is_skipped_not_unindexed(monkeypatch):
    """The distinction the whole band vocabulary exists to preserve."""
    monkeypatch.delenv("ASTA_API_KEY", raising=False)
    report = probe("10.1038/x")
    assert report.band == "skipped"
    assert not report.measured
    assert "not the same as the paper being unindexed" in report.reason


def test_probe_reads_the_rows():
    def handler(request):
        assert request.url.params["paperIds"] == "10.1038/x"
        assert request.headers["x-api-key"] == "k"
        return httpx.Response(200, json={"data": full_rows()})

    with client_returning(handler) as client:
        assert probe("10.1038/x", client=client, key="k").band == "full"


def test_a_paper_semantic_scholar_has_never_heard_of():
    def handler(request):
        return httpx.Response(404, text="no papers matching")

    with client_returning(handler) as client:
        report = probe("10.1038/x", client=client, key="k")
    assert report.band == "not_in_s2"


def test_a_broken_service_is_skipped_so_the_waterfall_keeps_going():
    def handler(request):
        return httpx.Response(503, text="upstream is sad")

    with client_returning(handler) as client:
        report = probe("10.1038/x", client=client, key="k")
    assert report.band == "skipped"
    assert not report.measured


def test_a_transport_failure_is_skipped_too():
    def handler(request):
        raise httpx.ConnectError("no route to host")

    with client_returning(handler) as client:
        assert probe("10.1038/x", client=client, key="k").band == "skipped"


def test_search_snippets_raises_on_a_bad_status():
    def handler(request):
        return httpx.Response(500, text="boom")

    with client_returning(handler) as client, pytest.raises(PaperAccessError, match="500"):
        search_snippets("10.1038/x", client=client, key="k")
