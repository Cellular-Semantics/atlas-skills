"""The supplements record: descriptions, the manifest boundary, consistency."""

from __future__ import annotations

import pytest

from paper_access.supplements import (
    MANIFEST_MAX_BYTES,
    MAX_FILE_BYTES,
    SKIP_MEDIA,
    ArchiveMember,
    SupplementFile,
    SupplementRetrieval,
    Supplements,
    cross_check_supplements,
    find_pointers,
    looks_like_manifest,
    media_type,
    pointer_gap,
    strip_markup,
)


def present(file_id: str = "table1.xlsx") -> SupplementFile:
    return SupplementFile(
        file_id=file_id,
        status="present",
        media_type="xlsx",
        size_bytes=1234,
        sha256="a" * 64,
        path=f"supplements/files/{file_id}",
        retrieval=SupplementRetrieval(route="europepmc_bundle", retrieved_at="2026-01-01T00:00:00+00:00"),
    )


# -- the manifest boundary ---------------------------------------------


@pytest.mark.parametrize(
    "name",
    ["manifest.txt", "MANIFEST.TXT", "index.csv", "README", "readme.md",
     "contents.txt", "file_list.csv", "filelist.tsv", "manifest_v2.txt"],
)
def test_a_bundle_index_may_be_read(name):
    assert looks_like_manifest(name, 2000)


@pytest.mark.parametrize(
    "name",
    ["table1.xlsx", "Supplementary Table 3.xlsx", "data.h5ad", "figure1.png",
     "results_index.xlsx", "supplementary_methods.pdf"],
)
def test_a_data_file_may_not(name):
    """The whole boundary of this phase. A spreadsheet is never a manifest,
    however it is named."""
    assert not looks_like_manifest(name, 2000)


def test_a_big_readme_is_a_manuscript_not_an_index():
    assert not looks_like_manifest("README.txt", MANIFEST_MAX_BYTES + 1)


def test_an_index_that_is_really_a_results_table():
    """`index.csv` passes on name and must fail on size once it is clearly data."""
    assert looks_like_manifest("index.csv", 1000)
    assert not looks_like_manifest("index.csv", 50 * 1024 * 1024)


def test_size_is_optional_so_a_listing_can_be_judged_before_download():
    assert looks_like_manifest("manifest.txt")


# -- descriptions -------------------------------------------------------


def test_a_description_is_stored_verbatim():
    entry = SupplementFile(file_id="x.xlsx")
    entry.describe("  Supplementary Tables 1-40.  ", "jats_caption")
    assert entry.description == "Supplementary Tables 1-40."
    assert entry.description_source == "jats_caption"


def test_the_first_source_wins_and_the_second_is_noted():
    """A blended description cannot be checked against anything, so the article
    XML's is kept and the other recorded beside it."""
    entry = SupplementFile(file_id="x.xlsx")
    entry.describe("Supplementary Tables 1-40.", "jats_caption")
    entry.describe("Tables for figures 2 and 4", "bundle_manifest")
    assert entry.description == "Supplementary Tables 1-40."
    assert entry.description_source == "jats_caption"
    assert "bundle_manifest says: Tables for figures 2 and 4" in entry.retrieval.note


def test_an_identical_second_description_is_not_noted_twice():
    entry = SupplementFile(file_id="x.xlsx")
    entry.describe("Same text", "jats_caption")
    entry.describe("Same text", "bundle_manifest")
    assert entry.retrieval.note is None


def test_an_empty_description_is_not_recorded():
    entry = SupplementFile(file_id="x.xlsx")
    entry.describe("   ", "jats_caption")
    assert entry.description is None


# -- merging a listing --------------------------------------------------


def test_add_merges_rather_than_duplicating():
    found = Supplements()
    found.add(SupplementFile(file_id="x.xlsx", label="Supplementary Table 1"))
    found.add(SupplementFile(file_id="x.xlsx", size_bytes=99, media_type="xlsx"))
    assert len(found.files) == 1
    assert found.files[0].label == "Supplementary Table 1"
    assert found.files[0].size_bytes == 99


def test_counts_are_by_status():
    found = Supplements(files=[
        present("a.xlsx"),
        SupplementFile(file_id="b.xlsx", status="deferred"),
        SupplementFile(file_id="c.xlsx", status="listed"),
    ])
    assert found.counts == {"present": 1, "deferred": 1, "listed": 1}


def test_round_trip():
    found = Supplements(
        files=[present(), SupplementFile(
            file_id="bundle.zip", status="present", media_type="zip",
            size_bytes=10, sha256="b" * 64, path="supplements/files/bundle.zip",
            retrieval=SupplementRetrieval(route="manual", retrieved_at="2026-01-01T00:00:00+00:00"),
            members=[ArchiveMember("inner.csv", True, "csv", 5, "supplements/unpacked/bundle.zip/inner.csv")],
        )],
        gaps=[{"what": "x", "reason": "y"}],
    )
    assert Supplements.from_dict(found.to_dict()).to_dict() == found.to_dict()


# -- consistency --------------------------------------------------------


def test_a_good_block_is_consistent():
    assert cross_check_supplements(Supplements(files=[present()]).to_dict()) == []


def test_present_without_a_path_is_rejected():
    entry = present()
    entry.path = None
    assert any("path is missing" in p for p in cross_check_supplements(
        Supplements(files=[entry]).to_dict()))


def test_present_needs_a_route_that_produced_it():
    entry = present()
    entry.retrieval = SupplementRetrieval(route="jats_listing")
    problems = cross_check_supplements(Supplements(files=[entry]).to_dict())
    assert any("no route is recorded as having produced it" in p for p in problems)


def test_a_listed_file_with_a_path_is_rejected():
    entry = SupplementFile(file_id="x.xlsx", status="listed", path="supplements/files/x.xlsx")
    assert any("a stored path is set" in p for p in cross_check_supplements(
        Supplements(files=[entry]).to_dict()))


def test_a_deferral_must_say_why():
    """Otherwise a reader cannot tell it from a file nobody could get."""
    entry = SupplementFile(file_id="x.xlsx", status="deferred")
    problems = cross_check_supplements(
        Supplements(files=[entry], gaps=[{"what": "x", "reason": "y", "file_id": "x.xlsx"}]).to_dict())
    assert any("nothing says why" in p for p in problems)


def test_a_deferral_must_have_a_gap_naming_what_would_fetch_it():
    entry = SupplementFile(
        file_id="x.xlsx", status="deferred",
        retrieval=SupplementRetrieval(route="europepmc_bundle", note="too big"),
    )
    problems = cross_check_supplements(Supplements(files=[entry]).to_dict())
    assert any("no gap says what would fetch it" in p for p in problems)


def test_a_description_with_no_source_is_rejected():
    entry = present()
    payload = Supplements(files=[entry]).to_dict()
    payload["files"][0]["description"] = "something a reader wrote"
    problems = cross_check_supplements(payload)
    assert any("cannot be told apart from one somebody wrote" in p for p in problems)


def test_a_source_with_no_description_is_rejected():
    payload = Supplements(files=[present()]).to_dict()
    payload["files"][0]["description_source"] = "jats_caption"
    assert any("carries no description" in p for p in cross_check_supplements(payload))


def test_a_duplicate_file_id_is_rejected():
    payload = Supplements(files=[present(), present()]).to_dict()
    assert any("listed twice" in p for p in cross_check_supplements(payload))


def test_a_member_marked_extracted_needs_somewhere_stored():
    entry = present("bundle.zip")
    entry.media_type = "zip"
    entry.members = [ArchiveMember("inner.csv", extracted=True)]
    assert any("nowhere stored" in p for p in cross_check_supplements(
        Supplements(files=[entry]).to_dict()))


def test_a_member_not_extracted_must_not_have_a_path():
    entry = present("bundle.zip")
    entry.members = [ArchiveMember("inner.csv", extracted=False, path="somewhere")]
    assert any("not extracted but has a path" in p for p in cross_check_supplements(
        Supplements(files=[entry]).to_dict()))


# -- repository pointers ------------------------------------------------


def test_accessions_are_found_with_their_sentence():
    text = (
        "Data availability. Raw sequencing data are deposited in GEO under "
        "accession GSE123456. Code is at https://figshare.com/articles/foo/123."
    )
    found = find_pointers(text)
    kinds = {(p["repository"], p["accession"]) for p in found}
    assert ("GEO", "GSE123456") in kinds
    assert any(r == "figshare" for r, _ in kinds)
    assert "deposited in GEO" in next(p for p in found if p["repository"] == "GEO")["context"]


def test_an_accession_found_in_passing_is_flagged_as_weaker():
    found = find_pointers("We reanalysed GSE999111 from an earlier study.")
    assert found and "in passing" in found[0]["note"]


def test_a_pointer_becomes_a_gap_that_does_not_promise_a_download():
    gap = pointer_gap({"repository": "Zenodo", "accession": "10.5281/zenodo.123",
                       "context": "Available at Zenodo."})
    assert "does not fetch from arbitrary hosts" in gap["reason"]
    assert "yourself" in gap["action"]


def test_no_pointers_in_ordinary_prose():
    assert find_pointers("We identified 5,322 clusters across 12 regions.") == []


def test_media_type_guesses_the_container_only():
    assert media_type("x.xlsx") == "xlsx"
    assert media_type("x.XLSX") == "xlsx"
    assert media_type("x.unknownext") == ""


# -- the blocker: numbers are not booleans ------------------------------


def test_a_zero_byte_supplement_is_present_not_missing():
    """A zero-byte member of an author-manuscript bundle made the record
    unwritable, so every later run died at the same write and the paper could
    not be re-attempted. `not 0` is not `is None`."""
    entry = present("f0008.gif")
    entry.size_bytes = 0
    assert cross_check_supplements(Supplements(files=[entry]).to_dict()) == []


@pytest.mark.parametrize("field_name", ["size_bytes", "bytes_transferred"])
def test_every_numeric_field_tolerates_zero(field_name):
    """The guard that matters more than the fix: the next numeric field will be
    written the same way."""
    entry = present()
    setattr(entry, field_name, 0)
    payload = Supplements(files=[entry]).to_dict()
    assert field_name in payload["files"][0]
    assert cross_check_supplements(payload) == []


def test_a_missing_size_is_still_caught():
    entry = present()
    entry.size_bytes = None
    assert any("size_bytes is missing" in p
               for p in cross_check_supplements(Supplements(files=[entry]).to_dict()))


# -- skipped is a decision, not an absence ------------------------------


def test_a_skip_must_say_why():
    entry = SupplementFile(file_id="fig.png", status="skipped")
    problems = cross_check_supplements(Supplements(files=[entry]).to_dict())
    assert any("nothing says why it was passed over" in p for p in problems)


def test_a_skip_needs_no_gap():
    """A gap is a question for a person, and nobody needs asking about a file
    we did not want."""
    entry = SupplementFile(
        file_id="fig.png", status="skipped",
        retrieval=SupplementRetrieval(route="europepmc_bundle",
                                      note="png is not wanted at any size"),
    )
    assert cross_check_supplements(Supplements(files=[entry]).to_dict()) == []


# -- accessions and markup ----------------------------------------------


def test_an_accession_is_not_truncated_by_the_context_clip():
    """Reproduced from testing: a block of E-MTAB-10000..10059 yielded
    `E-MTAB-100`, truncated from `E-MTAB-10039` and indistinguishable from a
    real hit sitting beside forty of them."""
    block = ("Arrays are in ArrayExpress under accessions "
             + ", ".join(f"E-MTAB-{n}" for n in range(10000, 10060))
             + " and were processed.")
    found = [p["accession"] for p in find_pointers(block)]
    assert len(found) == 60
    assert all(len(a.rsplit("-", 1)[1]) == 5 for a in found), [
        a for a in found if len(a.rsplit("-", 1)[1]) != 5
    ]


def test_context_is_clipped_on_a_word_boundary():
    long_tail = " ".join(["word"] * 400)
    found = find_pointers(f"Data availability: GSE123456 and then {long_tail}.")
    context = found[0]["context"]
    assert context.endswith("…")
    assert "wor…" not in context


def test_markup_never_reaches_a_gap():
    """Observed from testing: an action string carried
    `(2019)</xref> <ext-link xmlns:xlink="http://www.w3.org/1999/xlink" ...`."""
    xml = ('<p>Sequences were deposited (Smith <xref ref-type="bibr" rid="b1">2019</xref>) '
           'in GEO under GSE123456 <ext-link xmlns:xlink="http://www.w3.org/1999/xlink" '
           'xlink:href="http://x">here</ext-link>.</p>')
    pointer = find_pointers(xml)[0]
    for forbidden in ("<", ">", "xmlns:", "ext-link", "xref"):
        assert forbidden not in pointer["context"], pointer["context"]
    assert "deposited" in pointer["context"]
    assert forbidden not in pointer_gap(pointer)["action"]


def test_entities_are_stripped_too():
    assert "&amp;" not in strip_markup("Smith &amp; Jones deposited GSE1 here.")


# -- one media policy ----------------------------------------------------


def test_video_and_figures_are_not_wanted_at_any_size():
    for kind in ("mp4", "mov", "avi", "png", "jpg", "tif", "eps", "svg"):
        assert kind in SKIP_MEDIA


def test_tables_are_wanted_however_large():
    for kind in ("csv", "tsv", "xlsx", "xls", "mtx", "h5ad"):
        assert kind not in SKIP_MEDIA


def test_the_byte_limit_is_a_backstop_not_the_policy():
    """A 226 MB video was fetched on size grounds while 46 small tables were
    refused. The limit is generous because media type is what decides."""
    assert MAX_FILE_BYTES >= 200 * 1024 * 1024


def test_every_figure_and_video_extension_resolves_to_a_skipped_media_type():
    """A media type absent from the table is skipped by nothing: an
    author-manuscript bundle is mostly GIFs, and `.gif` was not in it."""
    for suffix in (".png", ".jpg", ".jpeg", ".tif", ".tiff", ".gif", ".bmp",
                   ".webp", ".eps", ".svg", ".mp4", ".mov", ".avi", ".mkv"):
        kind = media_type(f"figure{suffix}")
        assert kind, suffix
        assert kind in SKIP_MEDIA, suffix
