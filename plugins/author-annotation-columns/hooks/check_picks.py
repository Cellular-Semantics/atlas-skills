#!/usr/bin/env python3
"""Check a picks.json report against its schema and the obs it names.

Each column in a report claims to exist in obs. A picker that invents, misspells
or recases a name, or picks a portal field, writes a report that reads perfectly
well and is wrong, and a summary written from it hides the mistake. This
rejects the write instead, and tells the model which name failed and the
nearest real one.

Self-scoping: it acts only on a file named ``picks.json`` that looks like a
report. A ``{dataset_id: ...}`` scoring file, the other picks.json in this
repo, has none of a report's keys and is left alone.

The checking itself is ``obs-column-eval check-picks``, in the package, where it
is unit-tested. This is a shim. ``OBS_COLUMN_EVAL_BIN`` points it at a local
install instead of the pinned release, for iterating on the checker.

PostToolUse on Write and Edit.

Exit codes:
    0 -- not a report, or a report that passes
    2 -- a report that fails; Claude sees stderr
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

# One literal, not two concatenated: the release tooling finds pins by pattern.
PACKAGE = "obs-column-eval[check] @ git+https://github.com/Cellular-Semantics/atlas-skills@pkg-obs-column-eval--v0.4.0#subdirectory=packages/obs-column-eval"

REPORT_KEYS = {"schema_version", "source", "requested", "picks", "reasoning"}


def looks_like_a_report(path: Path) -> bool:
    try:
        body = json.loads(path.read_text())
    except (OSError, UnicodeDecodeError):
        return False
    except json.JSONDecodeError:
        # Meant as a report and broken: that is for the checker to say.
        return True
    return isinstance(body, dict) and bool(REPORT_KEYS & body.keys())


def main() -> int:
    try:
        hook_input = json.loads(sys.stdin.read())
    except (json.JSONDecodeError, OSError):
        return 0
    if not isinstance(hook_input, dict):
        return 0

    tool_input = hook_input.get("tool_input") or {}
    file_path = tool_input.get("file_path") or tool_input.get("path") or ""
    if not file_path:
        return 0

    path = Path(file_path)
    if path.name != "picks.json" or not path.is_file() or not looks_like_a_report(path):
        return 0

    local = os.environ.get("OBS_COLUMN_EVAL_BIN", "").strip()
    command = ([local] if local
               else ["uvx", "--from", PACKAGE, "obs-column-eval"])
    try:
        proc = subprocess.run(
            [*command, "check-picks", str(path)],
            capture_output=True,
            text=True,
            timeout=120,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        # A checker that cannot run must not look like a checker that passed.
        print(f"obs-column-eval check-picks could not run ({exc}); the columns "
              f"in {path} are unchecked", file=sys.stderr)
        return 0

    if proc.returncode == 0:
        return 0
    if proc.returncode != 1:
        # Not a verdict on the report: the checker itself failed.
        print(f"obs-column-eval check-picks failed (exit {proc.returncode}); the "
              f"columns in {path} are unchecked\n{proc.stderr}", file=sys.stderr)
        return 0

    sys.stderr.write(proc.stderr)
    sys.stderr.write("Fix picks.json from the pickers' own answers: copy each "
                     "column name exactly as obs spells it. Do not report a "
                     "column that fails this check.\n")
    return 2


if __name__ == "__main__":
    sys.exit(main())
