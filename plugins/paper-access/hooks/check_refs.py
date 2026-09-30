#!/usr/bin/env python3
"""Check the identifiers in a written document against the paper store.

A DOI or a PMID quoted in a report is an assertion about which paper a claim
came from, and a recalled one is wrong in a way no reader can detect. This
checks every identifier in a document against the records in a store, and
rejects the write if any of them is not there.

Self-scoping: it does nothing unless ``PAPER_ACCESS_STORE`` names a store. That
keeps it off every unrelated markdown file in the session, and makes it obvious
when the check is and is not running.

The checking itself is `paper-access check-refs`, in the package, where it is
unit-tested. This is a shim.

PostToolUse on Write and Edit.

Exit codes:
    0 — nothing to check, or every identifier accounted for
    2 — an identifier is not in the store; Claude sees stderr
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

PACKAGE = (
    "git+https://github.com/Cellular-Semantics/atlas-skills"
    "@pkg-paper-access--v0.1.0#subdirectory=packages/paper-access"
)

CHECKED_SUFFIXES = {".md", ".markdown", ".txt", ".json", ".yaml", ".yml"}


def main() -> int:
    store = os.environ.get("PAPER_ACCESS_STORE", "").strip()
    if not store:
        return 0

    try:
        hook_input = json.loads(sys.stdin.read())
    except (json.JSONDecodeError, OSError):
        return 0

    tool_input = hook_input.get("tool_input") or {}
    file_path = tool_input.get("file_path") or tool_input.get("path") or ""
    if not file_path:
        return 0

    path = Path(file_path)
    if path.suffix.lower() not in CHECKED_SUFFIXES or not path.exists():
        return 0
    # The store's own records are written by the CLI and are not prose.
    if path.name == "availability.json":
        return 0

    try:
        proc = subprocess.run(
            ["uvx", "--from", PACKAGE, "paper-access", "check-refs",
             str(path), "--store", store],
            capture_output=True,
            text=True,
            timeout=120,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        # A checker that cannot run must not look like a checker that passed.
        print(f"paper-access check-refs could not run ({exc}); identifiers in "
              f"{path.name} are unchecked", file=sys.stderr)
        return 0

    if proc.returncode == 0:
        return 0

    sys.stderr.write(proc.stdout)
    sys.stderr.write(proc.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
