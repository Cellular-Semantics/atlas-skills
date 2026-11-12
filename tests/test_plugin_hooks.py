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
import subprocess
import sys
from pathlib import Path

import pytest

HOOKS = Path(__file__).resolve().parent.parent / "plugins" / "paper-access" / "hooks"

DENY = HOOKS / "deny_record_write.py"
CHECK_REFS = HOOKS / "check_refs.py"


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
def test_a_report_naming_an_invented_column_is_blocked(tmp_path):
    result = run_picks(picks_report(tmp_path, ["author_cell_type", "celltype.l3"]))
    assert result.returncode == 2
    assert "`celltype.l3` is not a column" in result.stderr
    # Not just a refusal: what to do about it.
    assert "copy each column name exactly" in result.stderr


@needs_checker
def test_a_recased_column_is_blocked_with_the_real_name(tmp_path):
    result = run_picks(picks_report(tmp_path, ["Author_Cell_Type"]))
    assert result.returncode == 2
    assert "did you mean `author_cell_type`" in result.stderr


@needs_checker
def test_a_report_that_is_not_json_is_blocked(tmp_path):
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

