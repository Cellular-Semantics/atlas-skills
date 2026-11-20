#!/usr/bin/env python3
"""Check a paper's supplement manifest, and the disk behind it, after a fetch.

The manifest is the ``supplements`` block of ``availability.json``, and it
makes claims: this file is stored here, it is this big, it has this digest, this
archive member was extracted. A fetch that was interrupted, a store that was
moved or cleaned, or a file removed by hand leaves a manifest that still reads
well and is wrong. This runs straight after ``supplements fetch``, ``unpack`` or
``adopt`` and says which paper and which entry no longer holds.

It does not stop the command: a PostToolUse hook runs after it. Exit 2 sends
stderr back to the model, which is what gets the file re-fetched or reported
missing instead of described.

Self-scoping: it acts only on a Bash command that ran ``paper-access ...
supplements fetch|unpack|adopt``, with or without an alias or a ``uvx --from``
prefix. If the store cannot be found in the command, it does nothing.

The checking itself is ``paper-access supplements check``, in the package, where
it is unit-tested. This is a shim. ``PAPER_ACCESS_BIN`` points it at a local
executable instead of the pinned release, for iterating on the checker.

Exit codes:
    0 -- not a supplements command, nothing to check, or every manifest holds
    2 -- a manifest does not hold; Claude sees stderr
"""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
from pathlib import Path

# One literal, not two concatenated: the release tooling finds pins by pattern.
PACKAGE = "https://github.com/Cellular-Semantics/atlas-skills/archive/refs/tags/pkg-paper-access--v0.3.3.tar.gz#subdirectory=packages/paper-access"

WATCHED = {"fetch", "unpack", "adopt"}
SEPARATORS = {"&&", "||", ";", "|", "&"}


def parse(command: str) -> tuple[str | None, list[str]] | None:
    """The store and selection flags of a watched supplements command.

    ``None`` when the command is not one. Several chained commands: the last
    watched one wins, since that is the state the disk is left in.
    """
    try:
        words = shlex.split(command)
    except ValueError:
        return None
    segments: list[list[str]] = [[]]
    for word in words:
        if word in SEPARATORS:
            segments.append([])
        else:
            segments[-1].append(word)

    found: tuple[str | None, list[str]] | None = None
    for seg in segments:
        # The subcommand is the word after `supplements`, once the program has
        # been named; `paper-access` may sit behind an alias or `uvx --from X`.
        if not any(Path(w).name == "paper-access" for w in seg):
            continue
        try:
            at = seg.index("supplements")
        except ValueError:
            continue
        if at + 1 >= len(seg) or seg[at + 1] not in WATCHED:
            continue
        found = _flags(seg[at + 2:])
    return found


def _flags(args: list[str]) -> tuple[str | None, list[str]]:
    store: str | None = None
    selection: list[str] = []
    i = 0
    while i < len(args):
        word = args[i]
        name, eq, value = word.partition("=")
        if name in ("--store", "--id", "--input"):
            if not eq:
                i += 1
                value = args[i] if i < len(args) else ""
            if value:
                if name == "--store":
                    store = value
                else:
                    selection += [name, value]
        elif word == "--all":
            selection.append("--all")
        i += 1
    return store, selection


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
    command = tool_input.get("command")
    if not isinstance(command, str) or not command:
        return 0

    parsed = parse(command)
    if parsed is None:
        return 0
    store, selection = parsed
    if not store or not selection:
        return 0

    cwd = hook_input.get("cwd")
    if isinstance(cwd, str) and cwd and not os.path.isabs(os.path.expanduser(store)):
        store = str(Path(cwd) / store)
    store = os.path.expanduser(store)
    # A relative --input is read by the checker from its own cwd.
    if "--input" in selection and isinstance(cwd, str) and cwd:
        i = selection.index("--input") + 1
        if not os.path.isabs(selection[i]):
            selection[i] = str(Path(cwd) / selection[i])

    local = os.environ.get("PAPER_ACCESS_BIN", "").strip()
    base = [local] if local else ["uvx", "--from", PACKAGE, "paper-access"]
    try:
        proc = subprocess.run(
            [*base, "supplements", "check", "--store", store, *selection],
            capture_output=True,
            text=True,
            timeout=120,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        # A checker that cannot run must not look like a checker that passed.
        print(f"paper-access supplements check could not run ({exc}); the "
              f"manifests in {store} are unchecked", file=sys.stderr)
        return 0

    if proc.returncode == 0:
        return 0
    try:
        report = json.loads(proc.stdout)
        papers = report["papers"]
    except (json.JSONDecodeError, KeyError, TypeError):
        report = None
    if proc.returncode not in (1, 2) or report is None:
        print(f"paper-access supplements check failed (exit {proc.returncode}); "
              f"the manifests in {store} are unchecked\n{proc.stderr}", file=sys.stderr)
        return 0

    lines = []
    unchecked = []
    for paper, result in papers.items():
        for problem in result.get("problems") or []:
            lines.append(f"  {paper}: {problem}")
        # A paper that errored (most often: never fetched) has no manifest to
        # contradict, and the command itself already said why. Not a failure.
        if result.get("error"):
            unchecked.append(paper)
    if not lines:
        what = ", ".join(unchecked) if unchecked else f"the manifests in {store}"
        print(f"paper-access supplements check found nothing it could check for "
              f"{what}; unchecked\n{proc.stderr}", file=sys.stderr)
        return 0
    sys.stderr.write("The supplement manifest does not match what is stored:\n"
                     + "\n".join(lines) + "\n"
                     "Re-run the fetch for these papers with --retry, or report the "
                     "file as missing. Do not describe a file that is not on disk. "
                     "Never edit availability.json: only the CLI writes it.\n")
    return 2


if __name__ == "__main__":
    sys.exit(main())
