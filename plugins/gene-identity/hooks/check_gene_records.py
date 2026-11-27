#!/usr/bin/env python3
"""Check a .gene-records.json straight after it is written.

A record names a gene by ID and official symbol. An ID typed from memory, a
symbol copied from the source's wording, or a human gene in a mouse record
reads perfectly well and is wrong, and anything built on the file inherits
it. This runs ``gene-id check`` on the file: the schema, then every gene
against Translator NodeNormalization (exists and is current, official
symbol, species within the record's taxon) and against the log of IDs
``gene-id resolve`` returned. Problems go back to the model by record and
field, so the file is fixed before anything is said from it.

It does not stop the write: a PostToolUse hook runs after the file is on
disk, and it checks exactly what was written rather than a replay of an edit.
Exit 2 sends stderr back to the model.

Self-scoping: it acts only on a file whose name ends in ``.gene-records.json``:
the path of a Write/Edit/MultiEdit, or each such path a Bash command names (a
heredoc or redirection writes the file without any of those tools).

The checking is ``gene-id check``, in the package, where it is unit-tested.
This is a shim. ``GENE_ID_BIN`` points it at a local install instead of the
pinned release, for iterating on the checker.

Exit codes:
    0 -- not a records file, a file that passes, or a check that could not
         run. Exit 0 stderr never reaches the model, so "unchecked" is also
         sent as ``additionalContext`` on stdout, which does.
    2 -- a file that fails (including one that is not JSON); the file is
         written, and Claude sees stderr
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

# One literal, not two concatenated: the release tooling finds pins by pattern.
PACKAGE = "https://github.com/Cellular-Semantics/atlas-skills/archive/refs/tags/pkg-gene-identity--v0.3.1.tar.gz#subdirectory=packages/gene-identity"

SUFFIX = ".gene-records.json"


BASH_PATH = re.compile(r"""[^\s'"<>|;&()=]+\.gene-records\.json""")


def records_paths(hook_input: dict) -> list[str]:
    tool_input = hook_input.get("tool_input") or {}
    if not isinstance(tool_input, dict):
        return []
    command = tool_input.get("command")
    if isinstance(command, str):
        return list(dict.fromkeys(BASH_PATH.findall(command)))
    file_path = tool_input.get("file_path") or tool_input.get("path") or ""
    if isinstance(file_path, str) and file_path.endswith(SUFFIX):
        return [file_path]
    return []


def check_file(path: Path) -> tuple[int, str, str]:
    """``(exit code, problems for the model, unchecked notice)`` for one file."""
    try:
        json.loads(path.read_text())
    except ValueError as exc:
        return 2, (f"{path} is not valid JSON ({exc}). Write the whole record again "
                   "as a JSON array, then it can be checked.\n"), ""
    except OSError:
        return 0, "", ""

    local = os.environ.get("GENE_ID_BIN", "").strip()
    command = [local] if local else ["uvx", "-q", "--from", PACKAGE, "gene-id"]
    try:
        proc = subprocess.run([*command, "check", str(path)],
                              capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.TimeoutExpired) as exc:
        # A checker that cannot run must not look like a checker that passed.
        return 0, "", (f"gene-id check could not run ({exc}); the genes in {path} "
                       "are unchecked")
    if proc.returncode == 0:
        # Pass, possibly with lookups that could not run: say so.
        return 0, "", (proc.stderr if "UNCHECKED" in proc.stderr else "")
    if proc.returncode != 2:
        # Not a verdict on the file: the checker itself failed.
        return 0, "", (f"gene-id check failed (exit {proc.returncode}); the genes in "
                       f"{path} are unchecked\n{proc.stderr}")
    return 2, proc.stderr + (
        "Fix the records from the lookup's own output: take each ncbi_gene_id and the "
        "gene's official symbol (`label`) from `gene-id resolve`, in a species within the "
        "record's taxon. Do not report a record that fails this check.\n"), ""


def main() -> int:
    try:
        hook_input = json.loads(sys.stdin.read())
    except (json.JSONDecodeError, OSError):
        return 0
    if not isinstance(hook_input, dict):
        return 0

    code, problems, notices = 0, [], []
    for file_path in records_paths(hook_input):
        path = Path(file_path)
        if not path.is_absolute():
            cwd = hook_input.get("cwd")
            if isinstance(cwd, str) and cwd:
                path = Path(cwd) / path
        if not path.is_file():
            continue
        rc, bad, unchecked = check_file(path)
        code = max(code, rc)
        if bad:
            problems.append(bad)
        if unchecked:
            notices.append(unchecked)

    if code == 2:
        sys.stderr.write("".join(problems))
        return 2
    if notices:
        text = "\n".join(notices)
        sys.stderr.write(text if text.endswith("\n") else text + "\n")
        # Exit-0 stderr is not shown to the model; additionalContext is.
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": "PostToolUse", "additionalContext": text}}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
