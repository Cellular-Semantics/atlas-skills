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
