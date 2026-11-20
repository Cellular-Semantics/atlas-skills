"""``supplements check``: the manifest against the disk."""

from __future__ import annotations

import hashlib
import json
import os

import pytest

from paper_access import store
from paper_access.cli import main
from paper_access.ids import Identifier
from paper_access.record import Attempt, Availability, LocalSource, Metadata
from paper_access.supplements import check_on_disk

DOI = "10.1038/s41586-023-06812-z"
BODY = b"gene,logfc\nA,1.5\n"


def sha(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def manifest(**over) -> dict:
    """One present file and one archive with an extracted member."""
    present = {
        "file_id": "t1.csv", "status": "present", "media_type": "csv",
        "path": "supplements/files/t1.csv", "size_bytes": len(BODY),
        "sha256": sha(BODY), "retrieval": {"route": "europepmc_bundle"},
    }
    archive = {
        "file_id": "b.zip", "status": "present", "media_type": "zip",
        "path": "supplements/files/b.zip", "size_bytes": 4,
        "retrieval": {"route": "europepmc_bundle"},
        "members": [{"member_path": "d.csv", "extracted": True,
                     "path": "supplements/unpacked/b.zip/d.csv"}],
    }
    return {"files": [present, archive], **over}


@pytest.fixture
def pdir(tmp_path):
    root = tmp_path / "paper"
    (root / "supplements/files").mkdir(parents=True)
    (root / "supplements/unpacked/b.zip").mkdir(parents=True)
    (root / "supplements/files/t1.csv").write_bytes(BODY)
    (root / "supplements/files/b.zip").write_bytes(b"PK\x03\x04")
    (root / "supplements/unpacked/b.zip/d.csv").write_bytes(b"x")
    return root


def test_a_matching_store_is_clean(pdir):
    assert check_on_disk(manifest(), pdir) == []


def test_a_record_with_no_supplements_has_nothing_to_check(pdir):
    assert check_on_disk({"ids": {}}, pdir) == []
    assert check_on_disk({"supplements": None}, pdir) == []


def test_a_whole_record_is_read_by_its_supplements_key(pdir):
    assert check_on_disk({"supplements": manifest()}, pdir) == []
    (pdir / "supplements/files/t1.csv").unlink()
    assert check_on_disk({"supplements": manifest()}, pdir)


def test_a_missing_file_is_flagged(pdir):
    (pdir / "supplements/files/t1.csv").unlink()
    (problem,) = check_on_disk(manifest(), pdir)
    assert "t1.csv" in problem and "not on disk" in problem


def test_a_size_mismatch_is_flagged(pdir):
    (pdir / "supplements/files/t1.csv").write_bytes(BODY[:-3])
    problems = check_on_disk(manifest(), pdir)
    assert any("size_bytes" in p for p in problems)
    # With no digest recorded, the size alone is what catches it.
    block = manifest()
    del block["files"][0]["sha256"]
    (problem,) = check_on_disk(block, pdir)
    assert "size_bytes" in problem


def test_a_zero_size_agreement_passes(pdir):
    block = manifest()
    (pdir / "supplements/files/t1.csv").write_bytes(b"")
    block["files"][0].update(size_bytes=0, sha256=sha(b""))
    assert check_on_disk(block, pdir) == []


def test_a_wrong_digest_at_the_same_size_is_flagged(pdir):
    flipped = bytes([BODY[0] ^ 1]) + BODY[1:]
    (pdir / "supplements/files/t1.csv").write_bytes(flipped)
    (problem,) = check_on_disk(manifest(), pdir)
    assert "sha256" in problem


def test_no_digest_means_no_digest_check(pdir):
    block = manifest()
    del block["files"][0]["sha256"]
    flipped = bytes([BODY[0] ^ 1]) + BODY[1:]
    (pdir / "supplements/files/t1.csv").write_bytes(flipped)
    assert check_on_disk(block, pdir) == []


@pytest.mark.parametrize("bad", ["../outside.csv", "/etc/hosts", "supplements/../../x"])
def test_a_path_leaving_the_paper_directory_is_rejected(pdir, bad):
    # The target exists, so only the containment rule can reject it.
    (pdir.parent / "outside.csv").write_bytes(BODY)
    block = manifest()
    block["files"][0]["path"] = bad
    (problem,) = check_on_disk(block, pdir)
    assert "not inside the paper directory" in problem


def test_a_symlink_out_of_the_paper_directory_is_rejected(pdir, tmp_path):
    outside = tmp_path / "secret.csv"
    outside.write_bytes(BODY)
    link = pdir / "supplements/files/t1.csv"
    link.unlink()
    os.symlink(outside, link)
    (problem,) = check_on_disk(manifest(), pdir)
    assert "not inside the paper directory" in problem


def test_a_symlink_that_stays_inside_is_fine(pdir):
    link = pdir / "supplements/files/t1.csv"
    real = pdir / "supplements/real.csv"
    link.rename(real)
    os.symlink(real, link)
    assert check_on_disk(manifest(), pdir) == []


def test_a_missing_extracted_member_is_flagged(pdir):
    (pdir / "supplements/unpacked/b.zip/d.csv").unlink()
    (problem,) = check_on_disk(manifest(), pdir)
    assert "b.zip/d.csv" in problem and "not on disk" in problem


def test_an_extracted_member_path_escaping_the_directory_is_rejected(pdir):
    block = manifest()
    block["files"][1]["members"][0]["path"] = "../../etc/hosts"
    (problem,) = check_on_disk(block, pdir)
    assert "not inside the paper directory" in problem


def test_a_member_that_was_not_extracted_is_not_looked_for(pdir):
    block = manifest()
    block["files"][1]["members"].append(
        {"member_path": "fig.png", "extracted": False})
    assert check_on_disk(block, pdir) == []


def test_only_present_files_are_looked_for_on_disk(pdir):
    block = manifest()
    block["files"].append({"file_id": "gone.csv", "status": "missing",
                           "retrieval": {"route": "none"}})
    assert check_on_disk(block, pdir) == []


# -- the command --------------------------------------------------------


def a_record(doi: str = DOI) -> Availability:
    return Availability(
        input=doi,
        ids={"doi": Identifier.given(doi)},
        route="europepmc",
        local_source=LocalSource(kind="jats", path="source/paper.jats.xml",
                                 sha256="a" * 64, bytes=42),
        metadata=Metadata(source_api="europepmc",
                          retrieved_at="2026-01-01T00:00:00+00:00", title="An atlas"),
        attempts=[Attempt("europepmc", "ok")],
        fetched_at="2026-01-01T00:00:00+00:00",
    )


def seed(root, doi: str = DOI, block: dict | None = None):
    """A store with one paper whose record carries ``block``, written raw."""
    record = a_record(doi)
    path = store.write(root, record)
    body = json.loads(path.read_text())
    if block is not None:
        body["supplements"] = block
        path.write_text(json.dumps(body))
    return path.parent


def run(capsys, *argv):
    code = main(list(argv))
    out = capsys.readouterr().out
    return code, json.loads(out) if out.strip() else {}


def fill(pdir_):
    (pdir_ / "supplements/files").mkdir(parents=True)
    (pdir_ / "supplements/unpacked/b.zip").mkdir(parents=True)
    (pdir_ / "supplements/files/t1.csv").write_bytes(BODY)
    (pdir_ / "supplements/files/b.zip").write_bytes(b"PK\x03\x04")
    (pdir_ / "supplements/unpacked/b.zip/d.csv").write_bytes(b"x")


def test_a_clean_store_exits_0(tmp_path, capsys):
    fill(seed(tmp_path, block=manifest()))
    code, out = run(capsys, "supplements", "check", "--store", str(tmp_path), "--id", DOI)
    assert code == 0
    assert out["papers"][DOI] == {"problems": []}
    assert out["summary"]["with_problems"] == []


def test_a_paper_with_no_supplements_block_exits_0(tmp_path, capsys):
    seed(tmp_path)
    code, out = run(capsys, "supplements", "check", "--store", str(tmp_path), "--all")
    assert code == 0
    assert out["papers"][DOI]["problems"] == []


def test_a_missing_file_exits_2_and_names_it(tmp_path, capsys):
    pd = seed(tmp_path, block=manifest())
    fill(pd)
    (pd / "supplements/files/t1.csv").unlink()
    code, out = run(capsys, "supplements", "check", "--store", str(tmp_path), "--all")
    assert code == 2
    assert any("t1.csv" in p for p in out["papers"][DOI]["problems"])
    assert out["summary"]["with_problems"] == [DOI]


def test_the_schema_and_rules_are_checked_too(tmp_path, capsys):
    block = manifest()
    block["files"][0]["status"] = "skipped"   # path set on a skipped file
    fill(seed(tmp_path, block=block))
    code, out = run(capsys, "supplements", "check", "--store", str(tmp_path), "--all")
    assert code == 2
    assert out["papers"][DOI]["problems"]


def test_an_unknown_paper_is_an_error_exit_1(tmp_path, capsys):
    seed(tmp_path)
    code, out = run(capsys, "supplements", "check", "--store", str(tmp_path),
                    "--id", "10.1000/nothing")
    assert code == 1
    assert "error" in out["papers"]["10.1000/nothing"]


def test_input_file_and_a_sweep_report_each_paper(tmp_path, capsys):
    other = "10.1000/other"
    fill(seed(tmp_path, block=manifest()))
    pd2 = seed(tmp_path, other, block=manifest())
    fill(pd2)
    (pd2 / "supplements/files/t1.csv").unlink()
    ids = tmp_path / "ids.txt"
    ids.write_text(f"# papers\n{DOI}\n{other}\n")
    code, out = run(capsys, "supplements", "check", "--store", str(tmp_path),
                    "--input", str(ids))
    assert code == 2
    assert out["papers"][DOI]["problems"] == []
    assert out["papers"][other]["problems"]
    assert out["summary"]["checked"] == 2
