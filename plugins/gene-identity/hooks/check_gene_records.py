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

Self-scoping: it acts only on a file whose name ends in ``.gene-records.json``.

The checking is ``gene-id check``, in the package, where it is unit-tested.
This is a shim. ``GENE_ID_BIN`` points it at a local install instead of the
pinned release, for iterating on the checker.

Exit codes:
    0 -- not a records file, a file that passes, or a check that could not
         run (said on stderr: unchecked is not passed)
    2 -- a file that fails; the file is written, and Claude sees stderr
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

# One literal, not two concatenated: the release tooling finds pins by pattern.
PACKAGE = "https://github.com/Cellular-Semantics/atlas-skills/archive/refs/tags/pkg-gene-identity--v0.3.0.tar.gz#subdirectory=packages/gene-identity"

SUFFIX = ".gene-records.json"


def main() -> int:
    try:
        hook_input = json.loads(sys.stdin.read())
    except (json.JSONDecodeError, OSError):
        return 0
    if not isinstance(hook_input, dict):
        return 0

    tool_input = hook_input.get("tool_input") or {}
    if not isinstance(tool_input, dict):
        return 0
    file_path = tool_input.get("file_path") or tool_input.get("path") or ""
    if not isinstance(file_path, str) or not file_path.endswith(SUFFIX):
        return 0

    path = Path(file_path)
    if not path.is_absolute():
        cwd = hook_input.get("cwd")
        if isinstance(cwd, str) and cwd:
            path = Path(cwd) / path
    if not path.is_file():
        return 0

    local = os.environ.get("GENE_ID_BIN", "").strip()
    command = [local] if local else ["uvx", "--from", PACKAGE, "gene-id"]
    try:
        proc = subprocess.run(
            [*command, "check", str(path)],
            capture_output=True,
            text=True,
            timeout=120,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        # A checker that cannot run must not look like a checker that passed.
        print(f"gene-id check could not run ({exc}); the genes in {path} are unchecked",
              file=sys.stderr)
        return 0

    if proc.returncode == 0:
        # Pass, possibly with lookups that could not run: say so.
        if "UNCHECKED" in proc.stderr:
            sys.stderr.write(proc.stderr)
        return 0
    if proc.returncode != 2:
        # Not a verdict on the file: the checker itself failed.
        print(f"gene-id check failed (exit {proc.returncode}); the genes in {path} are "
              f"unchecked\n{proc.stderr}", file=sys.stderr)
        return 0

    sys.stderr.write(proc.stderr)
    sys.stderr.write(
        "Fix the records from the lookup's own output: take each ncbi_gene_id and the "
        "gene's official symbol (`label`) from `gene-id resolve`, in a species within the "
        "record's taxon. Do not report a record that fails this check.\n")
    return 2


if __name__ == "__main__":
    sys.exit(main())
