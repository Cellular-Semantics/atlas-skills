#!/usr/bin/env python3
"""Deny any direct write to a paper availability record.

An `availability.json` carries identifiers and publication metadata, and every
value in it is either something the caller supplied or something an API
returned. An agent editing the file is, by construction, writing a value with
neither provenance — a recalled DOI or a remembered title. That is the one
failure mode the record exists to make impossible, and it is invisible
afterwards, so it is denied at the point of the write rather than validated
after it.

The one field a person or an agent may set is `notes`, which has its own
command (`paper-access note`) and cannot be mistaken for an identifier.

PreToolUse on Write, Edit and MultiEdit. Pure stdlib and no subprocess: this
runs on every file write in the session, so it has to be cheap.

Exit codes:
    0 — not a record; allow
    2 — a record; deny, and Claude sees stderr
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

RECORD_NAME = "availability.json"

MESSAGE = f"""\
{RECORD_NAME} is written by the paper-access CLI and by nothing else.

Every identifier and every metadata value in it carries the provenance of where
it came from — the caller, or a named API at a recorded time. A hand-written
value has neither, and nothing downstream can tell it apart from a real one.

What you probably want instead:

  paper-access fetch  --store <store> --id <id>    walk the waterfall
  paper-access adopt  --store <store> --id <id> --file <path>
                                                   take in a supplied file
  paper-access note   --store <store> --id <id> --text "..."
                                                   the one free-text field
  paper-access show   --store <store> --id <id>    read the record

If the record is wrong, the fix is a CLI command or a bug in the CLI, never an
edit here."""


def main() -> int:
    try:
        hook_input = json.loads(sys.stdin.read())
    except (json.JSONDecodeError, OSError):
        return 0

    tool_input = hook_input.get("tool_input") or {}
    file_path = tool_input.get("file_path") or tool_input.get("path") or ""
    if not file_path:
        return 0

    if Path(file_path).name != RECORD_NAME:
        return 0

    print(MESSAGE, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
