"""The CLI contract: JSON on stdout, and exit codes a hook can key on.

Exit code 2 means "the thing you asked me to check does not check out". The
hooks in the plugin depend on it, so it is pinned here.
"""

from __future__ import annotations

import json

import pytest

from paper_access import record as record_module
from paper_access import store
from paper_access.cli import main
from paper_access.errors import PaperAccessError
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


# -- batch mode ----------------------------------------------------------


def test_a_sweep_runs_every_paper_and_summarises(capsys, populated, tmp_path, monkeypatch):
    """A corpus is the actual use case, and before this every sweep was a
    hand-rolled shell loop, which is where the timeouts went missing."""
    from paper_access.supplements import Supplements

    other = a_record()
    other.input = "10.1371/journal.pbio.3000410"
    other.ids = {"doi": Identifier.given("10.1371/journal.pbio.3000410")}
    store.write(populated, other)

    monkeypatch.setattr(
        "paper_access.cli.supp_flow.list_supplements",
        lambda record, store_root, **k: Supplements(),
    )
    code, payload = run(capsys, "supplements", "list", "--store", str(populated), "--all")
    assert code == 0
    assert set(payload["papers"]) == {DOI, "10.1371/journal.pbio.3000410"}
    assert payload["summary"]["attempted"] == 2
    assert payload["summary"]["errored"] == []


def test_a_sweep_from_a_file_of_identifiers(capsys, populated, tmp_path, monkeypatch):
    from paper_access.supplements import Supplements

    monkeypatch.setattr(
        "paper_access.cli.supp_flow.list_supplements",
        lambda record, store_root, **k: Supplements(),
    )
    listing = tmp_path / "ids.txt"
    listing.write_text(f"# the atlas\n{DOI}\n")
    code, payload = run(
        capsys, "supplements", "list", "--store", str(populated), "--input", str(listing)
    )
    assert code == 0 and list(payload["papers"]) == [DOI]


def test_a_sweep_reports_a_paper_that_errored_without_stopping(capsys, populated, monkeypatch):
    from paper_access.supplements import Supplements

    calls: list[str] = []

    def flaky(record, store_root, **k):
        calls.append(record.input)
        if len(calls) == 1:
            raise PaperAccessError("this one is broken")
        return Supplements()

    other = a_record()
    other.input = "10.1371/journal.pbio.3000410"
    other.ids = {"doi": Identifier.given("10.1371/journal.pbio.3000410")}
    store.write(populated, other)
    monkeypatch.setattr("paper_access.cli.supp_flow.list_supplements", flaky)

    code, payload = run(
        capsys, "supplements", "list", "--store", str(populated), "--all",
        "--concurrency", "1",
    )
    assert code == 1
    assert len(payload["summary"]["errored"]) == 1
    # The other paper was still attempted.
    assert len(calls) == 2


def test_a_sweep_with_nothing_to_do_says_so(capsys, tmp_path):
    assert main(["supplements", "list", "--store", str(tmp_path), "--all"]) == 1
    assert "no papers in" in capsys.readouterr().err


def test_exit_two_means_something_needs_a_decision(capsys, populated, monkeypatch):
    from paper_access.supplements import SupplementFile, SupplementRetrieval, Supplements

    deferred = Supplements(files=[
        SupplementFile(
            file_id="big.zip", status="deferred",
            retrieval=SupplementRetrieval(route="europepmc_bundle", note="too big"),
        )
    ])
    deferred.gaps = [{"what": "big.zip", "reason": "too big", "file_id": "big.zip"}]
    monkeypatch.setattr(
        "paper_access.cli.supp_flow.list_supplements", lambda r, s, **k: deferred
    )
    monkeypatch.setattr(
        "paper_access.cli.supp_flow.fetch_supplements", lambda r, s, **k: deferred
    )
    code, _ = run(capsys, "supplements", "fetch", "--store", str(populated), "--all")
    assert code == 2
    # ...and --skip-large is how a sweep says "carry on".
    code, _ = run(
        capsys, "supplements", "fetch", "--store", str(populated), "--all", "--skip-large"
    )
    assert code == 0


# -- migration -----------------------------------------------------------


def test_an_older_record_is_read_and_upgraded_on_write(capsys, tmp_path):
    """v0.2.0 refused v1 outright, so a 30-paper store had to be re-fetched
    over the network to get anywhere."""
    payload = a_record().to_dict()
    payload["schema_version"] = 1
    payload.pop("supplements", None)
    directory = tmp_path / "10.1038_s41586-023-06812-z"
    directory.mkdir()
    (directory / "availability.json").write_text(json.dumps(payload))

    found = store.read(tmp_path, DOI)
    assert found is not None

    code, result = run(capsys, "migrate", "--store", str(tmp_path))
    assert code == 0
    assert result["migrated"] and result["migrated"][0]["from"] == 1
    assert result["schema_version"] == record_module.SCHEMA_VERSION

    again = json.loads((directory / "availability.json").read_text())
    assert again["schema_version"] == record_module.SCHEMA_VERSION
    # Upgrading does not invent a supplements block: absent still means
    # nobody has looked, which is exactly true of a v1 record.
    assert "supplements" not in again


def test_a_record_from_the_future_is_still_refused(tmp_path):
    payload = a_record().to_dict()
    payload["schema_version"] = 99
    directory = tmp_path / "10.1038_s41586-023-06812-z"
    directory.mkdir()
    (directory / "availability.json").write_text(json.dumps(payload))
    with pytest.raises(PaperAccessError, match="newer than"):
        store.read(tmp_path, DOI)


def test_migrate_on_an_already_current_store_changes_nothing(capsys, populated):
    code, result = run(capsys, "migrate", "--store", str(populated))
    assert code == 0 and result["migrated"] == []
