"""The plugin hooks' contract, exercised the way the harness runs them.

These live at the repo root rather than in a package, because they test the
*plugin* — the scripts under ``plugins/``, invoked as subprocesses with hook
JSON on stdin, which is exactly how Claude Code calls them. A package test
reaching into ``plugins/`` would couple the two in the direction the layout
forbids.

What matters here is the exit code. A hook that exits 2 blocks the tool call
and shows its stderr to the model; one that exits 0 waves it through. Getting
that backwards either wrecks the session or silently disables the check, and
neither shows up anywhere else.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

HOOKS = Path(__file__).resolve().parent.parent / "plugins" / "paper-access" / "hooks"

DENY = HOOKS / "deny_record_write.py"
CHECK_REFS = HOOKS / "check_refs.py"
CHECK_SUPP = HOOKS / "check_supplements.py"


def run(script: Path, payload, env: dict[str, str] | None = None):
    """Invoke a hook the way the harness does: JSON on stdin, read the code."""
    body = payload if isinstance(payload, str) else json.dumps(payload)
    return subprocess.run(
        [sys.executable, str(script)],
        input=body,
        capture_output=True,
        text=True,
        env={"PATH": "/usr/bin:/bin", **(env or {})},
    )


def write_of(path: str) -> dict:
    return {"tool_name": "Write", "tool_input": {"file_path": path}}


# -- the record-write ban ----------------------------------------------


def test_a_write_to_a_record_is_denied():
    result = run(DENY, write_of("/project/papers/10.1038_x/availability.json"))
    assert result.returncode == 2


def test_the_denial_says_what_to_do_instead():
    """A bare refusal would leave the model guessing; the alternatives are the
    whole point of the message."""
    result = run(DENY, write_of("/x/availability.json"))
    assert "paper-access adopt" in result.stderr
    assert "paper-access note" in result.stderr
    # The message wraps, so match on a phrase that cannot straddle a break.
    assert "a bug in the CLI" in result.stderr


def test_an_unrelated_write_is_waved_through():
    result = run(DENY, write_of("/project/report.md"))
    assert result.returncode == 0
    assert result.stderr == ""


def test_a_similarly_named_file_is_not_a_record():
    """The match is on the exact filename, so a note about availability is
    not mistaken for the record itself."""
    for path in (
        "/x/availability.json.bak",
        "/x/my-availability.json",
        "/x/availability.md",
    ):
        assert run(DENY, write_of(path)).returncode == 0


@pytest.mark.parametrize(
    "payload",
    ["", "not json at all", "{}", '{"tool_input": {}}', '{"tool_input": null}'],
)
def test_malformed_hook_input_does_not_block_the_session(payload):
    """A hook that crashes on an unexpected payload blocks every write in the
    session, which is far worse than missing one check."""
    assert run(DENY, payload).returncode == 0


def test_an_edit_carrying_a_path_under_another_key():
    """Different tools name the path differently; the hook reads both."""
    assert run(DENY, {"tool_input": {"path": "/x/availability.json"}}).returncode == 2


# -- the citation check -------------------------------------------------


def test_the_refs_check_is_off_unless_a_store_is_named():
    """Self-scoping: without PAPER_ACCESS_STORE it must not fire on every
    markdown file in the session, and must not pay a uvx cold start to find
    that out."""
    result = run(CHECK_REFS, write_of("/project/report.md"))
    assert result.returncode == 0
    assert result.stderr == ""


def test_the_refs_check_ignores_the_records_themselves(tmp_path):
    record = tmp_path / "availability.json"
    record.write_text("{}")
    result = run(
        CHECK_REFS,
        write_of(str(record)),
        env={"PAPER_ACCESS_STORE": str(tmp_path)},
    )
    assert result.returncode == 0


def test_the_refs_check_ignores_a_file_it_cannot_read(tmp_path):
    result = run(
        CHECK_REFS,
        write_of(str(tmp_path / "gone.md")),
        env={"PAPER_ACCESS_STORE": str(tmp_path)},
    )
    assert result.returncode == 0


def test_a_checker_that_cannot_run_says_so_rather_than_passing_quietly(tmp_path):
    """uvx absent must read as 'unchecked', never as 'checked and fine'."""
    doc = tmp_path / "report.md"
    doc.write_text("see 10.1038/s41586-023-06812-z")
    result = run(
        CHECK_REFS,
        write_of(str(doc)),
        env={"PAPER_ACCESS_STORE": str(tmp_path), "PATH": "/nonexistent"},
    )
    assert result.returncode == 0
    assert "unchecked" in result.stderr


# -- the manifest the harness reads ------------------------------------


def test_the_hooks_manifest_wires_both_scripts_to_the_right_events():
    manifest = json.loads((HOOKS / "hooks.json").read_text())
    events = manifest["hooks"]

    pre = json.dumps(events["PreToolUse"])
    assert "deny_record_write.py" in pre
    # The ban has to land before the write, not after it: a record validated
    # afterwards has already been overwritten.
    assert "Write" in events["PreToolUse"][0]["matcher"]

    post = json.dumps(events["PostToolUse"])
    assert "check_refs.py" in post
    assert "check_supplements.py" in post
    assert "deny_record_write.py" not in post


def test_every_command_in_the_manifest_points_at_a_script_that_exists():
    manifest = json.loads((HOOKS / "hooks.json").read_text())
    for entries in manifest["hooks"].values():
        for entry in entries:
            for hook in entry["hooks"]:
                command = hook["command"]
                assert "${CLAUDE_PLUGIN_ROOT}" in command
                name = command.rsplit("/", 1)[-1].rstrip('"')
                assert (HOOKS / name).is_file(), name


def test_a_record_carrying_supplements_is_denied_just_the_same():
    """The supplements block lives inside availability.json, so retrieval is
    protected by the ban already shipped — but only if the match is on the
    filename rather than on anything about the contents."""
    result = run(DENY, write_of("/x/10.1038_y/availability.json"))
    assert result.returncode == 2


# -- author-annotation-columns: the picks check ------------------------

PICKS_HOOKS = HOOKS.parent.parent / "author-annotation-columns" / "hooks"
CHECK_PICKS = PICKS_HOOKS / "check_picks.py"

# The installed checker, so the hook is exercised end to end without uvx or
# the network. CI installs obs-column-eval into the same environment.
LOCAL_CHECKER = Path(sys.executable).parent / "obs-column-eval"
needs_checker = pytest.mark.skipif(not LOCAL_CHECKER.exists(),
                                   reason="obs-column-eval is not installed here")


def picks_report(tmp_path: Path, cell_type: list[str]) -> Path:
    """A report beside a TSV obs: TSV so these tests need no pyarrow."""
    (tmp_path / "obs.tsv").write_text("\tauthor_cell_type\tOrgan\nc1\tT\tlung\n")
    path = tmp_path / "picks.json"
    path.write_text(json.dumps({
        "schema_version": 1, "source": "obs.tsv", "requested": ["cell_type"],
        "picks": {"cell_type": cell_type},
        "reasoning": {"author-celltype-picker": "author labels"},
    }))
    return path


def run_picks(path: Path, **env: str):
    return run(CHECK_PICKS, write_of(str(path)),
               env={"OBS_COLUMN_EVAL_BIN": str(LOCAL_CHECKER), **env})


@needs_checker
def test_a_report_naming_real_columns_passes(tmp_path):
    result = run_picks(picks_report(tmp_path, ["author_cell_type"]))
    assert result.returncode == 0, result.stderr
    assert result.stderr == ""


@needs_checker
def test_a_report_naming_an_invented_column_is_flagged(tmp_path):
    result = run_picks(picks_report(tmp_path, ["author_cell_type", "celltype.l3"]))
    assert result.returncode == 2
    assert "`celltype.l3` is not a column" in result.stderr
    # Not just a refusal: what to do about it.
    assert "copy each column name exactly" in result.stderr


@needs_checker
def test_a_recased_column_is_flagged_with_the_real_name(tmp_path):
    result = run_picks(picks_report(tmp_path, ["Author_Cell_Type"]))
    assert result.returncode == 2
    assert "did you mean `author_cell_type`" in result.stderr


@needs_checker
def test_a_report_that_is_not_json_is_flagged(tmp_path):
    path = tmp_path / "picks.json"
    path.write_text("{\"picks\": ")
    assert run_picks(path).returncode == 2


def test_only_a_file_named_picks_json_is_checked(tmp_path):
    other = tmp_path / "report.json"
    other.write_text(json.dumps({"picks": {"cell_type": ["nope"]}}))
    result = run(CHECK_PICKS, write_of(str(other)),
                 env={"OBS_COLUMN_EVAL_BIN": "/nonexistent"})
    assert result.returncode == 0
    assert result.stderr == ""


def test_a_scoring_picks_file_is_not_mistaken_for_a_report(tmp_path):
    """`obs-column-eval score` reads `{dataset_id: ...}` files that are also
    called picks.json. They have none of a report's keys."""
    path = tmp_path / "picks.json"
    path.write_text(json.dumps({"0054013c": {"picks": ["x"], "reasoning": "y"}}))
    result = run(CHECK_PICKS, write_of(str(path)),
                 env={"OBS_COLUMN_EVAL_BIN": "/nonexistent"})
    assert result.returncode == 0
    assert result.stderr == ""


def test_a_picks_checker_that_cannot_run_says_so(tmp_path):
    """A missing checker must read as 'unchecked', never as 'checked and fine',
    and must not block the session."""
    result = run_picks(picks_report(tmp_path, ["nope"]),
                       OBS_COLUMN_EVAL_BIN="/nonexistent/obs-column-eval")
    assert result.returncode == 0
    assert "unchecked" in result.stderr


@pytest.mark.parametrize(
    "payload",
    ["", "not json at all", "[]", "{}", '{"tool_input": {}}', '{"tool_input": null}'],
)
def test_malformed_input_does_not_block_a_picks_write(payload):
    assert run(CHECK_PICKS, payload).returncode == 0


def test_the_picks_manifest_runs_after_the_write():
    """PostToolUse: the check reads the file, so it has to be on disk."""
    manifest = json.loads((PICKS_HOOKS / "hooks.json").read_text())
    events = manifest["hooks"]
    assert set(events) == {"PostToolUse"}
    (entry,) = events["PostToolUse"]
    assert "Write" in entry["matcher"] and "Edit" in entry["matcher"]
    (hook,) = entry["hooks"]
    assert hook["command"].endswith('/hooks/check_picks.py"')
    assert "${CLAUDE_PLUGIN_ROOT}" in hook["command"]
    assert CHECK_PICKS.is_file()



# -- paper-access: the supplement manifest check -----------------------

PAPER_ACCESS_BIN = (HOOKS.parent.parent.parent / "packages" / "paper-access"
                    / ".venv" / "bin" / "paper-access")
needs_paper_access = pytest.mark.skipif(
    not PAPER_ACCESS_BIN.exists(), reason="paper-access is not installed here (run ./dev.sh)")

DOI = "10.1038/x1"
BODY = b"gene,logfc\nA,1.5\n"


def supp_store(tmp_path: Path, doi: str = DOI, **tweak) -> Path:
    """A one-paper store whose availability.json is written directly."""
    import hashlib

    pdir = tmp_path / "store" / doi.replace("/", "_")
    (pdir / "supplements" / "files").mkdir(parents=True)
    (pdir / "supplements" / "files" / "t1.csv").write_bytes(BODY)
    entry = {
        "file_id": "t1.csv", "status": "present", "media_type": "csv",
        "path": "supplements/files/t1.csv", "size_bytes": len(BODY),
        "sha256": hashlib.sha256(BODY).hexdigest(),
        "retrieval": {"route": "europepmc_bundle"},
    }
    entry.update(tweak)
    (pdir / "availability.json").write_text(json.dumps({
        "schema_version": 1, "input": doi, "ids": {"doi": {"value": doi, "from": "input"}},
        "route": "europepmc",
        "local_source": {"kind": "jats", "path": "source/paper.jats.xml",
                         "sha256": "a" * 64, "bytes": 42},
        "metadata": {"source_api": "europepmc", "retrieved_at": "2026-01-01T00:00:00+00:00",
                     "title": "An atlas"},
        "attempts": [{"route": "europepmc", "outcome": "ok"}],
        "fetched_at": "2026-01-01T00:00:00+00:00",
        "supplements": {"files": [entry]},
    }))
    return tmp_path / "store"


def bash_of(command: str, **extra) -> dict:
    return {"tool_name": "Bash", "tool_input": {"command": command}, **extra}


def run_supp(payload, **env: str):
    return run(CHECK_SUPP, payload, env={"PAPER_ACCESS_BIN": str(PAPER_ACCESS_BIN), **env})


def test_a_command_that_is_not_a_supplements_command_is_ignored(tmp_path):
    store = supp_store(tmp_path)
    for command in (
        f"ls {store}",
        f"paper-access fetch --store {store} --id {DOI}",
        f"paper-access supplements show --store {store} --id {DOI}",
        f"paper-access supplements list --store {store} --all",
        f"paper-access supplements check --store {store} --all",
    ):
        result = run_supp(bash_of(command), PAPER_ACCESS_BIN="/nonexistent")
        assert result.returncode == 0 and result.stderr == "", command


@needs_paper_access
def test_a_clean_store_passes(tmp_path):
    store = supp_store(tmp_path)
    result = run_supp(bash_of(f"paper-access supplements fetch --store {store} --id {DOI}"))
    assert result.returncode == 0, result.stderr
    assert result.stderr == ""


@needs_paper_access
def test_a_deleted_file_is_flagged_and_the_message_says_what_to_do(tmp_path):
    store = supp_store(tmp_path)
    (store / "10.1038_x1" / "supplements" / "files" / "t1.csv").unlink()
    result = run_supp(bash_of(f"paper-access supplements unpack --store {store} --id {DOI}"))
    assert result.returncode == 2
    assert DOI in result.stderr and "t1.csv" in result.stderr and "not on disk" in result.stderr
    assert "--retry" in result.stderr
    assert "Never edit availability.json" in result.stderr


@needs_paper_access
def test_a_wrong_digest_is_flagged(tmp_path):
    store = supp_store(tmp_path, sha256="b" * 64)
    result = run_supp(bash_of(f"paper-access supplements adopt --store {store} --id {DOI} "
                              "--incoming /somewhere"))
    assert result.returncode == 2
    assert "sha256" in result.stderr


@needs_paper_access
def test_a_path_escaping_the_store_is_flagged(tmp_path):
    (tmp_path / "store").mkdir()
    (tmp_path / "outside.csv").write_bytes(BODY)
    store = supp_store(tmp_path, path="../../outside.csv")
    result = run_supp(bash_of(f"paper-access supplements fetch --store {store} --id {DOI}"))
    assert result.returncode == 2
    assert "not inside the paper directory" in result.stderr


@needs_paper_access
def test_all_is_handled_and_every_failing_paper_is_named(tmp_path):
    store = supp_store(tmp_path, sha256="b" * 64)
    result = run_supp(bash_of(f"paper-access supplements fetch --store {store} --all --retry"))
    assert result.returncode == 2
    assert DOI in result.stderr


@needs_paper_access
def test_an_alias_a_uvx_prefix_and_a_chain_are_all_recognised(tmp_path):
    store = supp_store(tmp_path, sha256="b" * 64)
    for command in (
        f"uvx --from 'https://x/y.tar.gz#subdirectory=packages/paper-access' paper-access "
        f"supplements fetch --store={store} --id={DOI}",
        f"cd /tmp && paper-access supplements fetch --id {DOI} --store '{store}' | tail",
    ):
        assert run_supp(bash_of(command)).returncode == 2, command


@needs_paper_access
def test_a_relative_store_resolves_against_the_hook_cwd(tmp_path):
    supp_store(tmp_path, sha256="b" * 64)
    result = run_supp(bash_of(f"paper-access supplements fetch --store store --id {DOI}",
                              cwd=str(tmp_path)))
    assert result.returncode == 2


def test_a_command_with_no_store_or_selection_is_left_alone():
    for command in ("paper-access supplements fetch --id x",
                    "paper-access supplements fetch --store /s",
                    "paper-access supplements fetch --store 'unterminated"):
        result = run_supp(bash_of(command), PAPER_ACCESS_BIN="/nonexistent")
        assert result.returncode == 0 and result.stderr == "", command


@pytest.mark.parametrize(
    "payload",
    ["", "not json at all", "[]", "{}", '{"tool_input": {}}', '{"tool_input": null}',
     '{"tool_input": {"command": 7}}', '{"tool_input": "x"}'],
)
def test_malformed_input_does_not_block_a_supplements_command(payload):
    assert run_supp(payload).returncode == 0


def test_a_supplements_checker_that_cannot_run_says_so(tmp_path):
    store = supp_store(tmp_path)
    result = run_supp(bash_of(f"paper-access supplements fetch --store {store} --id {DOI}"),
                      PAPER_ACCESS_BIN="/nonexistent/paper-access")
    assert result.returncode == 0
    assert "unchecked" in result.stderr


def test_the_supplements_hook_runs_after_bash():
    manifest = json.loads((HOOKS / "hooks.json").read_text())
    (entry,) = [e for e in manifest["hooks"]["PostToolUse"]
                if "check_supplements.py" in json.dumps(e)]
    assert entry["matcher"] == "Bash"
    (hook,) = entry["hooks"]
    assert hook["command"].endswith('/hooks/check_supplements.py"')
    assert hook["timeout"] >= 120
    assert "supplement" in manifest["description"]
    assert CHECK_SUPP.is_file()


def test_a_paper_that_was_never_fetched_is_unchecked_not_flagged(tmp_path):
    """The command already said 'fetch the paper first'; the hook must not add
    a misleading 'retry' on top."""
    bin_ = Path(__file__).resolve().parents[1] / "packages/paper-access/.venv/bin/paper-access"
    if not bin_.exists():
        pytest.skip("paper-access venv not built; run ./dev.sh")
    script = Path(__file__).resolve().parents[1] / "plugins/paper-access/hooks/check_supplements.py"
    payload = {"tool_input": {"command":
               f"paper-access supplements fetch --store {tmp_path} --id PMC1"}}
    proc = subprocess.run(
        [sys.executable, str(script)], input=json.dumps(payload), capture_output=True,
        text=True, env={**os.environ, "PAPER_ACCESS_BIN": str(bin_)},
    )
    assert proc.returncode == 0
    assert "unchecked" in proc.stderr


# -- gene-identity: the gene records check ------------------------------

GENE_HOOKS = HOOKS.parent.parent / "gene-identity" / "hooks"
CHECK_GENES = GENE_HOOKS / "check_gene_records.py"

GENE_ID_BIN = Path(sys.executable).parent / "gene-id"
needs_gene_id = pytest.mark.skipif(not GENE_ID_BIN.exists(),
                                   reason="gene-identity is not installed here")

DRD1 = {"name": "D1", "taxon": "NCBITaxon:10090", "outcome": "GENE",
        "ncbi_gene_id": "NCBIGene:13488", "symbol": "Drd1", "gene_taxon": "NCBITaxon:10090",
        "method": "PAPER_DEFINITION", "rationale": "dopamine D1 receptor"}


def gene_cache(tmp_path: Path, resolved=("NCBIGene:13488",)) -> Path:
    """What earlier lookups would have left: Drd1 known, and in the resolve log."""
    d = tmp_path / "cache"
    d.mkdir()
    (d / "genes.json").write_text(json.dumps(
        {"NCBIGene:13488": {"label": "Drd1", "taxon": "NCBITaxon:10090"}}))
    (d / "resolved.json").write_text(json.dumps({i: {"name": "D1"} for i in resolved}))
    return d


def run_genes(payload, cache: Path, **env: str):
    # Nothing here may reach the network: an uncached lookup hits a closed port.
    return run(CHECK_GENES, payload, env={
        "GENE_ID_BIN": str(GENE_ID_BIN), "GENE_IDENTITY_CACHE": str(cache),
        "GENE_IDENTITY_NODENORM_URL": "http://127.0.0.1:9",
        "GENE_IDENTITY_EUTILS_URL": "http://127.0.0.1:9", **env})


def records_file(tmp_path: Path, records: list[dict], name="out.gene-records.json") -> Path:
    path = tmp_path / name
    path.write_text(json.dumps(records))
    return path


@needs_gene_id
def test_a_correct_record_passes(tmp_path):
    result = run_genes(write_of(str(records_file(tmp_path, [DRD1]))), gene_cache(tmp_path))
    assert result.returncode == 0, result.stderr
    assert result.stderr == ""


@needs_gene_id
def test_a_source_wording_symbol_is_flagged_with_the_official_one(tmp_path):
    rec = {**DRD1, "symbol": "D1"}
    result = run_genes(write_of(str(records_file(tmp_path, [rec]))), gene_cache(tmp_path))
    assert result.returncode == 2
    assert "is 'Drd1'" in result.stderr
    assert "from `gene-id resolve`" in result.stderr   # what to do, not just a refusal


@needs_gene_id
def test_an_id_the_lookup_never_returned_is_flagged(tmp_path):
    result = run_genes(write_of(str(records_file(tmp_path, [DRD1]))),
                       gene_cache(tmp_path, resolved=()))
    assert result.returncode == 2
    assert "never returned by `gene-id resolve`" in result.stderr


@needs_gene_id
def test_a_schema_violation_is_flagged(tmp_path):
    rec = {**DRD1, "kind": "GENE_FAMILY"}
    result = run_genes(write_of(str(records_file(tmp_path, [rec]))), gene_cache(tmp_path))
    assert result.returncode == 2 and "[0] (D1).kind" in result.stderr


@needs_gene_id
def test_an_uncached_gene_offline_is_unchecked_not_flagged(tmp_path):
    rec = {**DRD1, "ncbi_gene_id": "NCBIGene:20604", "symbol": "Sst"}
    result = run_genes(write_of(str(records_file(tmp_path, [rec]))),
                       gene_cache(tmp_path, resolved=("NCBIGene:20604",)))
    assert result.returncode == 0
    assert "UNCHECKED NCBIGene:20604" in result.stderr


@needs_gene_id
def test_a_relative_records_path_resolves_against_the_hook_cwd(tmp_path):
    records_file(tmp_path, [{**DRD1, "symbol": "D1"}])
    payload = {**write_of("out.gene-records.json"), "cwd": str(tmp_path)}
    assert run_genes(payload, gene_cache(tmp_path)).returncode == 2


@needs_gene_id
def test_a_records_file_that_is_not_json_is_sent_back(tmp_path):
    path = tmp_path / "out.gene-records.json"
    path.write_text('[{"name":"PV","outcome":"GENE",')
    result = run_genes(write_of(str(path)), gene_cache(tmp_path))
    assert result.returncode == 2 and "not valid JSON" in result.stderr


@needs_gene_id
def test_a_bash_write_of_a_records_file_is_checked(tmp_path):
    path = records_file(tmp_path, [{**DRD1, "symbol": "D1"}])
    payload = {"tool_name": "Bash", "cwd": str(tmp_path), "tool_input": {
        "command": f"cat > {path.name} <<'EOF'\n[]\nEOF"}}
    assert run_genes(payload, gene_cache(tmp_path)).returncode == 2


def test_a_bash_command_naming_no_records_file_is_ignored():
    payload = {"tool_input": {"command": "ls -la && echo records.json"}}
    result = run(CHECK_GENES, payload, env={"GENE_ID_BIN": "/nonexistent"})
    assert result.returncode == 0 and result.stderr == "" and result.stdout == ""


@needs_gene_id
def test_unchecked_reaches_the_model_as_additional_context(tmp_path):
    rec = {**DRD1, "ncbi_gene_id": "NCBIGene:20604", "symbol": "Sst"}
    result = run_genes(write_of(str(records_file(tmp_path, [rec]))),
                       gene_cache(tmp_path, resolved=("NCBIGene:20604",)))
    out = json.loads(result.stdout)["hookSpecificOutput"]
    assert out["hookEventName"] == "PostToolUse" and "UNCHECKED NCBIGene:20604" in out["additionalContext"]


def test_only_a_gene_records_file_is_checked(tmp_path):
    other = records_file(tmp_path, [{"nonsense": True}], name="records.json")
    result = run(CHECK_GENES, write_of(str(other)), env={"GENE_ID_BIN": "/nonexistent"})
    assert result.returncode == 0
    assert result.stderr == ""


def test_a_gene_checker_that_cannot_run_says_so(tmp_path):
    path = records_file(tmp_path, [DRD1])
    result = run(CHECK_GENES, write_of(str(path)),
                 env={"GENE_ID_BIN": "/nonexistent/gene-id"})
    assert result.returncode == 0
    assert "unchecked" in result.stderr


@pytest.mark.parametrize(
    "payload",
    ["", "not json at all", "[]", "{}", '{"tool_input": {}}', '{"tool_input": null}',
     '{"tool_input": {"file_path": 3}}'],
)
def test_malformed_input_does_not_block_a_gene_records_write(payload):
    assert run(CHECK_GENES, payload).returncode == 0


def test_the_gene_records_manifest_runs_after_the_write():
    """PostToolUse: the check reads the file, so it has to be on disk."""
    manifest = json.loads((GENE_HOOKS / "hooks.json").read_text())
    events = manifest["hooks"]
    assert set(events) == {"PostToolUse"}
    (entry,) = events["PostToolUse"]
    assert "Write" in entry["matcher"] and "Edit" in entry["matcher"]
    (hook,) = entry["hooks"]
    assert hook["command"].endswith('/hooks/check_gene_records.py"')
    assert "${CLAUDE_PLUGIN_ROOT}" in hook["command"]
    assert CHECK_GENES.is_file()
