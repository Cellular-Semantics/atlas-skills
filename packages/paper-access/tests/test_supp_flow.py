"""The supplement waterfall end to end, against a mocked network.

Everything offline: the bundle rungs run through an `httpx` MockTransport and
real in-memory zips, so the two failures that look like success — an empty body
and a short non-zip body — are exercised against the shapes Europe PMC actually
returns.
"""

from __future__ import annotations

import io
import zipfile

import httpx
import pytest

from paper_access import store, supp_flow, supp_sources
from paper_access.ids import Identifier
from paper_access.record import Attempt, Availability, LocalSource, Metadata

DOI = "10.1038/s41586-023-06812-z"
PMCID = "PMC10719114"

JATS = """<?xml version="1.0"?>
<article xmlns:xlink="http://www.w3.org/1999/xlink">
  <front><article-meta>
    <article-title>An atlas</article-title>
  </article-meta></front>
  <body>
    <sec><p>Data availability: raw data are in GEO under GSE123456.</p></sec>
  </body>
  <back>
    <sec>
      <supplementary-material id="S1" xlink:href="41586_2023_6812_MOESM1_ESM.xlsx">
        <label>Supplementary Table 1</label>
        <caption><p>Differential expression for every cluster.</p></caption>
      </supplementary-material>
      <supplementary-material id="S2">
        <label>Supplementary Video 1</label>
        <media xlink:href="41586_2023_6812_MOESM2_ESM.mp4"/>
      </supplementary-material>
      <supplementary-material id="S3" xlink:href="41586_2023_6812_MOESM3_ESM.png">
        <label>Supplementary Figure 1</label>
      </supplementary-material>
    </sec>
  </back>
</article>
"""


def make_zip(entries: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, body in entries.items():
            archive.writestr(name, body)
    return buffer.getvalue()


def xlsx_bytes(name: str = "sheet.xml") -> bytes:
    """A structurally valid xlsx, so verify_payload accepts it."""
    return make_zip({f"xl/{name}": b"<worksheet/>"})


@pytest.fixture
def paper(tmp_path):
    """A fetched paper with its article XML on disk."""
    record = Availability(
        input=DOI,
        ids={"doi": Identifier.given(DOI), "pmcid": Identifier.returned(PMCID, "europepmc")},
        route="europepmc",
        local_source=LocalSource(
            kind="jats", path="source/paper.jats.xml",
            sha256="a" * 64, bytes=len(JATS),
        ),
        metadata=Metadata(source_api="europepmc", retrieved_at="2026-01-01T00:00:00+00:00",
                          title="An atlas"),
        attempts=[Attempt("europepmc", "ok")],
        fetched_at="2026-01-01T00:00:00+00:00",
    )
    store.write(tmp_path, record)
    store.store_bytes(tmp_path, record, "jats", JATS.encode())
    return record, tmp_path


def client_for(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def bundle_only(head=None, get=None, on_get=None):
    """A network where only the Europe PMC bundle answers.

    Publisher-direct is tried before the bundle for a Springer DOI, so a
    handler that does not 404 it will be asked for files this test is not
    about.

    `head` is accepted for the size-decision tests and is served as the GET
    response's headers, because the real endpoint does not answer HEAD at all
    and the size is read from a streamed GET.
    """
    def handler(request):
        url = str(request.url)
        if "supplementaryFiles" not in url:
            return httpx.Response(404)
        if on_get is not None:
            return on_get(request)
        if get is not None:
            return get
        if head is not None:
            return head
        return httpx.Response(404)
    return handler


# -- listing ------------------------------------------------------------


def test_the_article_xml_gives_filenames_captions_and_labels(paper, monkeypatch):
    record, root = paper
    monkeypatch.delenv("ASTA_API_KEY", raising=False)
    found = supp_flow.list_supplements(record, root)

    ids = [f.file_id for f in found.files]
    assert ids == [
        "41586_2023_6812_MOESM1_ESM.xlsx",
        "41586_2023_6812_MOESM2_ESM.mp4",
        "41586_2023_6812_MOESM3_ESM.png",
    ]
    first = found.files[0]
    assert first.label == "Supplementary Table 1"
    assert first.description == "Differential expression for every cluster."
    assert first.description_source == "jats_caption"
    assert first.status == "listed"


def test_a_filename_on_a_nested_media_element_is_found(paper, monkeypatch):
    """Some publishers hang the href on <media> rather than the wrapper."""
    record, root = paper
    monkeypatch.delenv("ASTA_API_KEY", raising=False)
    found = supp_flow.list_supplements(record, root)
    assert found.by_id("41586_2023_6812_MOESM2_ESM.mp4") is not None


def test_a_data_availability_statement_becomes_a_gap_not_a_download(paper, monkeypatch):
    record, root = paper
    monkeypatch.delenv("ASTA_API_KEY", raising=False)
    found = supp_flow.list_supplements(record, root)
    geo = [g for g in found.gaps if "GSE123456" in g["what"]]
    assert geo and "does not fetch from arbitrary hosts" in geo[0]["reason"]


def test_the_index_is_only_asked_where_there_is_no_local_text(paper, monkeypatch):
    """A paper with XML on disk has something to grep, so the probe is not
    needed and must not be spent."""
    record, root = paper
    monkeypatch.setenv("ASTA_API_KEY", "k")
    called = []
    monkeypatch.setattr(
        supp_flow, "_asta_pointers",
        lambda *a, **k: (called.append(1), ([], "", "skipped"))[1],
    )
    supp_flow.list_supplements(record, root)
    assert not called


def test_a_paper_with_no_text_at_all_asks_the_index(tmp_path, monkeypatch):
    record = Availability(
        input=DOI,
        ids={"doi": Identifier.given(DOI)},
        route="asta",
        asta=None,
        attempts=[Attempt("asta_probe", "ok")],
    )
    record.route = "none"
    record.gap = {"what": DOI, "reason": "nothing worked"}
    store.write(tmp_path, record)
    monkeypatch.setattr(
        supp_flow, "_asta_pointers",
        lambda *a, **k: ([{"repository": "GEO", "accession": "GSE9", "context": "c"}],
                         "1 pointer", "ok"),
    )
    found = supp_flow.list_supplements(record, tmp_path)
    routes = {a.route: a.outcome for a in found.listing_sources}
    assert routes["asta_scan"] == "ok"
    assert any("GSE9" in g["what"] for g in found.gaps)


def test_no_article_xml_is_skipped_not_failed(tmp_path, monkeypatch):
    monkeypatch.delenv("ASTA_API_KEY", raising=False)
    record = Availability(
        input=DOI, ids={"doi": Identifier.given(DOI)}, route="none",
        gap={"what": DOI, "reason": "x"}, attempts=[Attempt("europepmc", "unavailable")],
    )
    store.write(tmp_path, record)
    found = supp_flow.list_supplements(record, tmp_path)
    routes = {a.route: a.outcome for a in found.listing_sources}
    assert routes["jats_listing"] == "skipped"


# -- the size decision --------------------------------------------------


def test_a_big_bundle_is_deferred_not_truncated(paper, monkeypatch):
    """The whole point: a limit nobody was told about would look like a paper
    with fewer supplements than it has."""
    record, root = paper
    monkeypatch.delenv("ASTA_API_KEY", raising=False)
    record.supplements = supp_flow.list_supplements(record, root)

    def big(request):
        # Declares half a gigabyte. The body must never be consumed.
        return httpx.Response(
            200, headers={"content-length": str(500_000_000)},
            content=b"x" * 1024,
        )

    handler = bundle_only(on_get=big)
    with client_for(handler) as http:
        found = supp_flow.fetch_supplements(
            record, root, client=http, large_bytes=50 * 1024 * 1024
        )

    assert all(f.status == "deferred" for f in found.files)
    bundle = next(a for a in found.attempts if a.route == "europepmc_bundle")
    assert bundle.outcome == "deferred"
    assert "500 MB" in bundle.note and "not downloaded without being asked" in bundle.note
    assert all("--yes-large" in g["action"] for g in found.gaps if g.get("file_id"))


def test_deferred_is_never_unavailable(paper, monkeypatch):
    record, root = paper
    monkeypatch.delenv("ASTA_API_KEY", raising=False)
    record.supplements = supp_flow.list_supplements(record, root)

    handler = bundle_only(on_get=lambda r: httpx.Response(
        200, headers={"content-length": str(500_000_000)}, content=b"x" * 16))
    with client_for(handler) as http:
        found = supp_flow.fetch_supplements(record, root, client=http)
    outcomes = {a.outcome for a in found.attempts if a.route == "europepmc_bundle"}
    assert "unavailable" not in outcomes


def test_an_undeclared_size_is_downloaded_up_to_the_threshold(paper, monkeypatch):
    """Europe PMC streams the bundle chunked and declares no length, so
    deferring on an undeclared size would disable the route for every paper.
    The download runs against the threshold instead, bounding what is wasted
    on finding out."""
    record, root = paper
    monkeypatch.delenv("ASTA_API_KEY", raising=False)
    record.supplements = supp_flow.list_supplements(record, root)

    # An iterator body makes the response chunked, so it carries no
    # content-length — which is what a real host doing the same looks like. A
    # bytes body would have httpx fill the header in and defeat the test.
    def chunked(request):
        return httpx.Response(200, content=iter([b"x" * 32]))

    handler = bundle_only(on_get=chunked)
    with client_for(handler) as http:
        found = supp_flow.fetch_supplements(record, root, client=http)
    bundle = next(a for a in found.attempts if a.route == "europepmc_bundle")
    # It was read, found not to be a zip, and recorded as such — not deferred.
    assert bundle.outcome == "unavailable"
    assert "not a zip" in bundle.note


def test_an_undeclared_size_that_turns_out_huge_is_abandoned(paper, monkeypatch):
    record, root = paper
    monkeypatch.delenv("ASTA_API_KEY", raising=False)
    record.supplements = supp_flow.list_supplements(record, root)

    def endless(request):
        return httpx.Response(200, content=iter([b"x" * 4096] * 64))

    with client_for(bundle_only(on_get=endless)) as http:
        found = supp_flow.fetch_supplements(record, root, client=http, large_bytes=1024)
    bundle = next(a for a in found.attempts if a.route == "europepmc_bundle")
    assert bundle.outcome == "deferred"
    assert "while downloading" in bundle.note
    assert all(f.status == "deferred" for f in found.files)


def test_yes_large_proceeds(paper, monkeypatch):
    record, root = paper
    monkeypatch.delenv("ASTA_API_KEY", raising=False)
    record.supplements = supp_flow.list_supplements(record, root)
    body = make_zip({"41586_2023_6812_MOESM1_ESM.xlsx": xlsx_bytes()})

    handler = bundle_only(
        head=httpx.Response(200, headers={"content-length": str(60_000_000)}),
        get=httpx.Response(200, content=body))

    with client_for(handler) as http:
        found = supp_flow.fetch_supplements(
            record, root, client=http, allow_large=True, use_bundle=True
        )
    got = found.by_id("41586_2023_6812_MOESM1_ESM.xlsx")
    assert got.status == "present"


# -- the two traps ------------------------------------------------------


def test_an_empty_body_is_unavailable_not_an_empty_archive(paper, monkeypatch):
    record, root = paper
    monkeypatch.delenv("ASTA_API_KEY", raising=False)
    record.supplements = supp_flow.list_supplements(record, root)

    handler = bundle_only(
        head=httpx.Response(200, headers={"content-length": "0"}),
        get=httpx.Response(200, content=b""))

    with client_for(handler) as http:
        found = supp_flow.fetch_supplements(record, root, client=http, allow_large=True)
    bundle = next(a for a in found.attempts if a.route == "europepmc_bundle")
    assert bundle.outcome == "unavailable"
    assert "zero bytes" in bundle.note


def test_a_short_non_zip_body_is_unavailable(paper, monkeypatch):
    """Europe PMC answers 200 with 165 bytes for a paper whose full text is not
    open. Recorded naively the paper looks as though it has no supplements."""
    record, root = paper
    monkeypatch.delenv("ASTA_API_KEY", raising=False)
    record.supplements = supp_flow.list_supplements(record, root)

    handler = bundle_only(
        head=httpx.Response(200, headers={"content-length": "165"}),
        get=httpx.Response(200, content=b"x" * 165))

    with client_for(handler) as http:
        found = supp_flow.fetch_supplements(record, root, client=http, allow_large=True)
    bundle = next(a for a in found.attempts if a.route == "europepmc_bundle")
    assert bundle.outcome == "unavailable"
    assert "not a zip" in bundle.note


def test_a_truncated_workbook_is_discarded_rather_than_recorded(paper, monkeypatch):
    """A route can hand back the wrong size and unopenable, and Europe PMC does.
    Kept with a digest it would look authoritative and fail much later."""
    record, root = paper
    monkeypatch.delenv("ASTA_API_KEY", raising=False)
    record.supplements = supp_flow.list_supplements(record, root)
    body = make_zip({"41586_2023_6812_MOESM1_ESM.xlsx": b"not really a workbook"})

    handler = bundle_only(
        head=httpx.Response(200, headers={"content-length": str(len(body))}),
        get=httpx.Response(200, content=body))

    with client_for(handler) as http:
        found = supp_flow.fetch_supplements(record, root, client=http)
    got = found.by_id("41586_2023_6812_MOESM1_ESM.xlsx")
    assert got.status == "missing"
    assert got.sha256 is None
    assert "discarded" in got.retrieval.note


# -- what gets extracted ------------------------------------------------


def test_figure_images_are_listed_but_not_extracted(paper, monkeypatch):
    record, root = paper
    monkeypatch.delenv("ASTA_API_KEY", raising=False)
    record.supplements = supp_flow.list_supplements(record, root)
    body = make_zip({
        "41586_2023_6812_MOESM1_ESM.xlsx": xlsx_bytes(),
        "41586_2023_6812_MOESM3_ESM.png": b"\x89PNG" + b"0" * 100,
    })

    handler = bundle_only(
        head=httpx.Response(200, headers={"content-length": str(len(body))}),
        get=httpx.Response(200, content=body))

    with client_for(handler) as http:
        found = supp_flow.fetch_supplements(record, root, client=http)

    png = found.by_id("41586_2023_6812_MOESM3_ESM.png")
    assert png.status != "present"
    assert "figure image" in png.retrieval.note
    # But it is still on the record: a skip a reader cannot see is
    # indistinguishable from a file that was never there.
    assert png.size_bytes == 104


def test_an_oversized_member_is_deferred_with_a_gap(paper, monkeypatch):
    record, root = paper
    monkeypatch.delenv("ASTA_API_KEY", raising=False)
    record.supplements = supp_flow.list_supplements(record, root)
    body = make_zip({"41586_2023_6812_MOESM1_ESM.xlsx": xlsx_bytes()})

    handler = bundle_only(
        head=httpx.Response(200, headers={"content-length": str(len(body))}),
        get=httpx.Response(200, content=body))

    monkeypatch.setattr(supp_flow, "TABULAR_MEMBER_CAP_BYTES", 1)
    monkeypatch.setattr(supp_flow, "MEMBER_CAP_BYTES", 1)
    with client_for(handler) as http:
        found = supp_flow.fetch_supplements(record, root, client=http)
    entry = found.by_id("41586_2023_6812_MOESM1_ESM.xlsx")
    assert entry.status == "deferred"
    assert any(g.get("file_id") == entry.file_id for g in found.gaps)


def test_a_bundle_manifest_supplies_labels_and_a_data_file_does_not(paper, monkeypatch):
    record, root = paper
    monkeypatch.delenv("ASTA_API_KEY", raising=False)
    record.supplements = supp_flow.list_supplements(record, root)
    manifest = b"41586_2023_6812_MOESM4_ESM.csv - per-cell metadata for all donors\n"
    body = make_zip({
        "manifest.txt": manifest,
        "41586_2023_6812_MOESM4_ESM.csv": b"barcode,cell_type\n",
    })

    handler = bundle_only(
        head=httpx.Response(200, headers={"content-length": str(len(body))}),
        get=httpx.Response(200, content=body))

    with client_for(handler) as http:
        found = supp_flow.fetch_supplements(record, root, client=http)

    described = found.by_id("41586_2023_6812_MOESM4_ESM.csv")
    assert described.description == "per-cell metadata for all donors"
    assert described.description_source == "bundle_manifest"
    # The caption from the article XML is never overwritten by a manifest.
    from_xml = found.by_id("41586_2023_6812_MOESM1_ESM.xlsx")
    assert from_xml.description_source in (None, "jats_caption")


# -- publisher-direct ---------------------------------------------------


def test_springer_files_are_fetched_individually(paper, monkeypatch):
    """One 122 KB workbook, where the bundle would fetch everything round it."""
    record, root = paper
    monkeypatch.delenv("ASTA_API_KEY", raising=False)
    record.supplements = supp_flow.list_supplements(record, root)
    payload = xlsx_bytes()
    seen: list[str] = []

    def handler(request):
        seen.append(str(request.url))
        if "static-content.springer.com" in str(request.url):
            if str(request.url).endswith(".xlsx"):
                return httpx.Response(200, content=payload)
            return httpx.Response(404)
        return httpx.Response(404)

    with client_for(handler) as http:
        found = supp_flow.fetch_supplements(record, root, client=http, use_bundle=False)
    entry = found.by_id("41586_2023_6812_MOESM1_ESM.xlsx")
    assert entry.status == "present"
    assert entry.retrieval.route == "publisher_direct"
    assert any("esm" in u for u in seen)


def test_no_template_is_a_skip_not_a_failure(tmp_path, monkeypatch):
    monkeypatch.delenv("ASTA_API_KEY", raising=False)
    record = Availability(
        input="10.1126/science.adf1226",
        ids={"doi": Identifier.given("10.1126/science.adf1226")},
        route="none", gap={"what": "x", "reason": "y"},
        attempts=[Attempt("europepmc", "unavailable")],
    )
    store.write(tmp_path, record)
    record.supplements = supp_flow.list_supplements(record, tmp_path)
    record.supplements.add(
        __import__("paper_access.supplements", fromlist=["SupplementFile"]).SupplementFile(
            file_id="table.xlsx", status="listed")
    )
    with client_for(lambda r: httpx.Response(404)) as http:
        found = supp_flow.fetch_supplements(record, tmp_path, client=http)
    direct = next(a for a in found.attempts if a.route == "publisher_direct")
    assert direct.outcome == "skipped"
    assert "no URL template" in direct.note


# -- the negative cache -------------------------------------------------


def test_a_missing_file_is_not_re_requested(paper, monkeypatch):
    record, root = paper
    monkeypatch.delenv("ASTA_API_KEY", raising=False)
    record.supplements = supp_flow.list_supplements(record, root)
    calls: list[str] = []

    def handler(request):
        calls.append(str(request.url))
        return httpx.Response(404)

    with client_for(handler) as http:
        record.supplements = supp_flow.fetch_supplements(record, root, client=http)
    before = len(calls)
    with client_for(handler) as http:
        supp_flow.fetch_supplements(record, root, client=http)
    assert len(calls) == before


def test_retry_tries_again(paper, monkeypatch):
    record, root = paper
    monkeypatch.delenv("ASTA_API_KEY", raising=False)
    record.supplements = supp_flow.list_supplements(record, root)
    calls: list[str] = []

    def handler(request):
        calls.append(str(request.url))
        return httpx.Response(404)

    with client_for(handler) as http:
        record.supplements = supp_flow.fetch_supplements(record, root, client=http)
    before = len(calls)
    with client_for(handler) as http:
        supp_flow.fetch_supplements(record, root, client=http, retry=True)
    assert len(calls) > before


# -- unpacking ----------------------------------------------------------


def test_unpack_records_the_member_table_and_extracts_what_it_can(paper, monkeypatch):
    record, root = paper
    monkeypatch.delenv("ASTA_API_KEY", raising=False)
    record.supplements = supp_flow.list_supplements(record, root)
    inner = make_zip({"tables/deg.csv": b"gene,logfc\n", "figs/f1.png": b"\x89PNG"})

    from paper_access.supplements import SupplementFile
    entry = record.supplements.add(SupplementFile(file_id="bundle.zip", status="listed"))
    directory = supp_flow.supplements_dir(root, record) / "files"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "bundle.zip").write_bytes(inner)
    supp_flow._accept(entry, directory / "bundle.zip", directory, "manual")

    found = supp_flow.unpack(record, root)
    members = {m.member_path: m for m in found.by_id("bundle.zip").members}
    assert members["tables/deg.csv"].extracted
    assert members["tables/deg.csv"].path
    # Listed but not extracted, and the record says which.
    assert not members["figs/f1.png"].extracted
    assert "figure image" in members["figs/f1.png"].note


# -- adopting ------------------------------------------------------------


def test_adopt_matches_by_name_and_reports_what_it_could_not_place(paper, monkeypatch):
    record, root = paper
    monkeypatch.delenv("ASTA_API_KEY", raising=False)
    record.supplements = supp_flow.list_supplements(record, root)
    incoming = root / "incoming"
    incoming.mkdir()
    (incoming / "41586_2023_6812_MOESM1_ESM.xlsx").write_bytes(xlsx_bytes())
    (incoming / "something-else.xlsx").write_bytes(xlsx_bytes())

    found, unmatched = supp_flow.adopt(record, root, incoming)
    assert found.by_id("41586_2023_6812_MOESM1_ESM.xlsx").status == "present"
    assert found.by_id("41586_2023_6812_MOESM1_ESM.xlsx").retrieval.route == "manual"
    # Taken in under its own name rather than filed as something it is not.
    assert [u["file_id"] for u in unmatched] == ["something-else.xlsx"]


# -- the record stays valid ----------------------------------------------


def test_the_record_still_validates_after_every_stage(paper, monkeypatch):
    record, root = paper
    monkeypatch.delenv("ASTA_API_KEY", raising=False)
    record.supplements = supp_flow.list_supplements(record, root)
    store.write(root, record)

    body = make_zip({"41586_2023_6812_MOESM1_ESM.xlsx": xlsx_bytes()})

    handler = bundle_only(
        head=httpx.Response(200, headers={"content-length": str(len(body))}),
        get=httpx.Response(200, content=body))

    with client_for(handler) as http:
        record.supplements = supp_flow.fetch_supplements(record, root, client=http)
    store.write(root, record)

    record.supplements = supp_flow.unpack(record, root)
    path = store.write(root, record)
    assert path.is_file()

    reread = store.read(root, DOI)
    assert reread.supplements is not None
    assert reread.supplements.by_id("41586_2023_6812_MOESM1_ESM.xlsx").status == "present"


def test_a_404_is_unavailable_and_a_5xx_is_failed():
    """A host that answered has told us something; one that broke has not.
    Recording a timeout as unavailable would leave a retrievable bundle
    permanently marked unreachable."""
    with client_for(lambda r: httpx.Response(404)) as http:
        result = supp_sources.fetch_bundle(
            http, PMCID, large_bytes=1, max_bytes=2, allow_large=True)
    assert result.outcome == "unavailable"

    with client_for(lambda r: httpx.Response(503)) as http:
        result = supp_sources.fetch_bundle(
            http, PMCID, large_bytes=1, max_bytes=2, allow_large=True)
    assert result.outcome == "failed"


def test_a_transport_failure_is_failed_not_unavailable():
    """Observed live: the endpoint does not answer HEAD at all, and an earlier
    version read the resulting timeout as 'this article has no bundle'."""
    def boom(request):
        raise httpx.ReadTimeout("the read operation timed out")

    with client_for(boom) as http:
        result = supp_sources.fetch_bundle(
            http, PMCID, large_bytes=1, max_bytes=2, allow_large=True)
    assert result.outcome == "failed"
    assert "ReadTimeout" in result.note


def test_the_size_is_read_from_the_get_because_head_is_not_answered():
    """The endpoint hangs on HEAD and serves GET fine, so no HEAD is sent."""
    methods: list[str] = []

    def handler(request):
        methods.append(request.method)
        return httpx.Response(200, headers={"content-length": str(10**9)}, content=b"x")

    with client_for(handler) as http:
        result = supp_sources.fetch_bundle(
            http, PMCID, large_bytes=1000, max_bytes=10**9, allow_large=False)
    assert methods == ["GET"]
    assert result.outcome == "deferred"
    assert result.size_bytes == 10**9
    # Declared and over the threshold, so the body was never read.


def test_a_deliberately_skipped_figure_is_not_reported_as_missing(paper, monkeypatch):
    """Observed live: skipped figure images were swept into `missing` and each
    grew a gap asking somebody to go and find a file nobody wanted."""
    record, root = paper
    monkeypatch.delenv("ASTA_API_KEY", raising=False)
    record.supplements = supp_flow.list_supplements(record, root)
    body = make_zip({
        "41586_2023_6812_MOESM1_ESM.xlsx": xlsx_bytes(),
        "41586_2023_6812_MOESM3_ESM.png": b"\x89PNG" + b"0" * 100,
    })
    handler = bundle_only(get=httpx.Response(200, content=body))

    with client_for(handler) as http:
        found = supp_flow.fetch_supplements(record, root, client=http)

    png = found.by_id("41586_2023_6812_MOESM3_ESM.png")
    assert png.status == "listed"
    assert "deliberately not extracted" in png.retrieval.note
    assert not [g for g in found.gaps if g.get("file_id") == png.file_id]

    # A file no rung ever reached is still missing, and still gets a gap.
    absent = found.by_id("41586_2023_6812_MOESM2_ESM.mp4")
    assert absent.status == "missing"
    assert [g for g in found.gaps if g.get("file_id") == absent.file_id]
