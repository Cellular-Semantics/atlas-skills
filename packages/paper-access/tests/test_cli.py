"""The CLI contract: JSON on stdout, and exit codes a hook can key on.

Exit code 2 means "the thing you asked me to check does not check out". The
hooks in the plugin depend on it, so it is pinned here.
"""

from __future__ import annotations

import json

import pytest

from paper_access import store
from paper_access.cli import main
from paper_access.ids import Identifier
from paper_access.record import Attempt, Availability, LocalSource, Metadata

DOI = "10.1038/s41586-023-06812-z"


def a_record() -> Availability:
    return Availability(
        input=DOI,
        ids={"doi": Identifier.given(DOI)},
        route="europepmc",
        local_source=LocalSource(
            kind="jats", path="source/paper.jats.xml", sha256="a" * 64, bytes=42
        ),
        metadata=Metadata(
            source_api="europepmc",
            retrieved_at="2026-01-01T00:00:00+00:00",
            title="A high-resolution transcriptomic atlas",
        ),
        attempts=[Attempt("europepmc", "ok")],
        fetched_at="2026-01-01T00:00:00+00:00",
    )


@pytest.fixture
def populated(tmp_path):
    store.write(tmp_path, a_record())
    return tmp_path


def run(capsys, *argv) -> tuple[int, dict]:
    code = main(list(argv))
    out = capsys.readouterr().out
    return code, json.loads(out) if out.strip() else {}


def test_version_is_available():
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0


def test_schema_prints_the_contract(capsys):
    code, payload = run(capsys, "schema")
    assert code == 0
    assert payload["title"] == "PaperAvailability"


def test_show_returns_the_record_and_no_problems(capsys, populated):
    code, payload = run(capsys, "show", "--store", str(populated), "--id", DOI)
    assert code == 0
    assert payload["problems"] == []
    assert payload["record"]["route"] == "europepmc"


def test_show_on_a_paper_that_is_not_there(capsys, tmp_path):
    code, payload = run(capsys, "show", "--store", str(tmp_path), "--id", DOI)
    assert code == 1
    assert "no record" in payload["error"]


def test_check_exits_two_on_an_inconsistent_record(capsys, tmp_path):
    bad = tmp_path / "availability.json"
    payload = a_record().to_dict()
    del payload["local_source"]  # claims a route with nothing stored
    bad.write_text(json.dumps(payload))
    code, result = run(capsys, "check", str(bad))
    assert code == 2
    assert result["problems"]


def test_check_exits_zero_on_a_good_record(capsys, tmp_path):
    good = tmp_path / "availability.json"
    good.write_text(json.dumps(a_record().to_dict()))
    code, result = run(capsys, "check", str(good))
    assert code == 0
    assert result["problems"] == []


def test_check_on_something_that_is_not_json(capsys, tmp_path):
    path = tmp_path / "availability.json"
    path.write_text("{ not json")
    code, _ = run(capsys, "check", str(path))
    assert code == 2


def test_check_refs_exits_two_and_explains_on_stderr(capsys, populated, tmp_path):
    doc = tmp_path / "report.md"
    doc.write_text("As shown in 10.1016/j.cell.2021.04.048 ...")
    code = main(["check-refs", str(doc), "--store", str(populated)])
    captured = capsys.readouterr()
    assert code == 2
    assert "10.1016/j.cell.2021.04.048" in captured.err
    assert captured.out == ""


def test_check_refs_is_quiet_when_everything_is_accounted_for(capsys, populated, tmp_path):
    doc = tmp_path / "report.md"
    doc.write_text(f"As shown in {DOI} ...")
    assert main(["check-refs", str(doc), "--store", str(populated)]) == 0
    assert capsys.readouterr().err == ""


def test_report_prints_a_table_by_default(capsys, populated):
    assert main(["report", "--store", str(populated)]) == 0
    out = capsys.readouterr().out
    assert "europepmc" in out and "jats" in out


def test_report_json_is_machine_readable(capsys, populated):
    code, payload = run(capsys, "report", "--store", str(populated), "--json")
    assert code == 0
    assert payload["papers"][0]["id"] == DOI


def test_papers_lists_identifiers_one_per_line(capsys, populated):
    assert main(["papers", "--store", str(populated)]) == 0
    assert capsys.readouterr().out.strip() == DOI


def test_resolve_exits_two_when_something_needs_confirming(capsys, monkeypatch):
    monkeypatch.setattr(
        "paper_access.waterfall.sources.search_candidates",
        lambda *a, **k: [{"doi": DOI, "title": "A paper", "source_api": "europepmc"}],
    )
    code, payload = run(capsys, "resolve", "--id", "Yao 2023 mouse brain")
    assert code == 2
    assert payload["resolved"][0]["status"] == "candidates"


def test_resolve_exits_zero_for_exact_identifiers(capsys):
    code, payload = run(capsys, "resolve", "--id", DOI)
    assert code == 0
    assert payload["resolved"][0]["status"] == "confirmed"


def test_an_input_file_of_identifiers_with_comments(capsys, tmp_path):
    listing = tmp_path / "dois.txt"
    listing.write_text(f"# the atlas\n{DOI}\n\nPMC10769438\n")
    code, payload = run(capsys, "resolve", "--input", str(listing))
    assert code == 0
    assert [r["kind"] for r in payload["resolved"]] == ["doi", "pmcid"]


def test_nothing_to_do_is_an_error_not_a_silent_success(capsys):
    assert main(["resolve"]) == 1
    assert "pass --id or --input" in capsys.readouterr().err


def test_note_writes_the_one_free_text_field(capsys, populated):
    code, payload = run(
        capsys, "note", "--store", str(populated), "--id", DOI,
        "--text", "accepted manuscript",
    )
    assert code == 0
    assert payload["noted"]["notes"] == "accepted manuscript"


def test_candidates_describes_a_drop_zone(capsys, tmp_path):
    drop = tmp_path / "drop"
    drop.mkdir()
    (drop / "paper.xml").write_text(
        '<article><front><article-meta><article-title>A paper</article-title>'
        "</article-meta></front></article>"
    )
    code, payload = run(capsys, "candidates", "--inputs", str(drop))
    assert code == 0
    assert payload["candidates"][0]["title"] == "A paper"
