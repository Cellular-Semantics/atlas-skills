"""The command line. Every subcommand prints JSON on stdout.

Output is machine-readable by default because the caller is usually an agent,
and a table it has to parse out of prose is a table it will parse wrong. The
few commands with a human-facing view offer it behind ``--text``.

Exit codes are meaningful: 0 for success, 1 for an error, 2 for "the thing you
asked me to check does not check out". A hook keys on 2.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from . import __version__, refs, waterfall
from . import record as record_module
from .errors import PaperAccessError
from .store import read as read_record
from .store import read_all


def _emit(payload: Any) -> None:
    json.dump(payload, sys.stdout, indent=2, sort_keys=False)
    sys.stdout.write("\n")


def _ids_from(args: argparse.Namespace) -> list[str]:
    """The identifiers a command was given, from --id and --input together."""
    out: list[str] = list(args.id or [])
    if getattr(args, "input", None):
        path = Path(args.input)
        if not path.is_file():
            raise PaperAccessError(f"no such file: {path}")
        for line in path.read_text(encoding="utf-8").splitlines():
            text = line.strip()
            if text and not text.startswith("#"):
                out.append(text)
    if not out:
        raise PaperAccessError("nothing to do: pass --id or --input")
    return out


# ----------------------------------------------------------------------
# Commands
# ----------------------------------------------------------------------


def cmd_resolve(args: argparse.Namespace) -> int:
    results = [waterfall.resolve(raw, limit=args.limit) for raw in _ids_from(args)]
    _emit({"resolved": results})
    unresolved = [r for r in results if r["status"] != "confirmed"]
    return 0 if not unresolved else 2


def cmd_fetch(args: argparse.Namespace) -> int:
    out: list[dict[str, Any]] = []
    failures = 0
    for identifier in _ids_from(args):
        try:
            found = waterfall.fetch(
                identifier,
                args.store,
                retry=args.retry,
                allow_pdf=not args.no_pdf,
                probe_asta=not args.no_asta,
                contact=args.contact,
                asta_key=args.asta_key,
            )
        except PaperAccessError as exc:
            failures += 1
            out.append({"input": identifier, "error": str(exc)})
            continue
        out.append(found.to_dict())
    _emit({"fetched": out})
    return 1 if failures else 0


def cmd_show(args: argparse.Namespace) -> int:
    found = read_record(args.store, args.id)
    if found is None:
        _emit({"error": f"no record for {args.id} in {args.store}"})
        return 1
    payload = found.to_dict()
    problems = record_module.check(payload)
    _emit({"record": payload, "problems": problems})
    return 2 if problems else 0


def cmd_report(args: argparse.Namespace) -> int:
    rows = waterfall.report(args.store)
    if args.json:
        _emit({"papers": rows})
        return 0
    _print_report(rows)
    return 0


def _print_report(rows: list[dict[str, Any]]) -> None:
    if not rows:
        print("no papers in this store")
        return
    width = max(len(str(r["id"])) for r in rows)
    print(f"{'id'.ljust(width)}  {'route':<16} {'kind':<6} {'asta':<14} title")
    for row in rows:
        print(
            f"{str(row['id']).ljust(width)}  "
            f"{row['route']:<16} "
            f"{row.get('kind', '-'):<6} "
            f"{row.get('asta_band', '-'):<14} "
            f"{(row.get('title') or '')[:60]}"
        )
    gaps = [r for r in rows if r.get("gap")]
    if gaps:
        print(f"\n{len(gaps)} of {len(rows)} papers could not be retrieved:")
        for row in gaps:
            print(f"  {row['id']}: {row['gap']}")
    ast = [r for r in rows if r.get("asta_band") == "skipped"]
    if ast:
        print(
            f"\n{len(ast)} paper(s) were not probed, so their index coverage is "
            "unknown — which is not the same as unindexed. Set ASTA_API_KEY."
        )


def cmd_candidates(args: argparse.Namespace) -> int:
    _emit({"candidates": waterfall.candidates(args.inputs)})
    return 0


def cmd_adopt(args: argparse.Namespace) -> int:
    found = waterfall.adopt(args.id, args.store, args.file)
    _emit({"adopted": found.to_dict()})
    return 0


def cmd_note(args: argparse.Namespace) -> int:
    found = waterfall.note(args.id, args.store, args.text)
    _emit({"noted": found.to_dict()})
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    results = waterfall.verify(args.store)
    _emit({"verified": results})
    bad = [r for r in results if r["status"] == "mismatch"]
    return 2 if bad else 0


def cmd_check(args: argparse.Namespace) -> int:
    path = Path(args.record)
    if not path.is_file():
        _emit({"error": f"no such file: {path}"})
        return 1
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        _emit({"error": f"not valid JSON: {exc}"})
        return 2
    problems = record_module.check(payload)
    _emit({"file": str(path), "problems": problems})
    return 2 if problems else 0


def cmd_check_refs(args: argparse.Namespace) -> int:
    problems = refs.check_document(args.document, args.store)
    if not problems:
        return 0
    print(refs.describe(problems, args.document, args.store), file=sys.stderr)
    return 2


def cmd_schema(args: argparse.Namespace) -> int:
    _emit(record_module.schema())
    return 0


def cmd_papers(args: argparse.Namespace) -> int:
    """Identifiers in a store, one per line — for feeding another command."""
    for found in read_all(args.store):
        try:
            _, value = found.primary_id
        except PaperAccessError:
            continue
        print(value)
    return 0


# ----------------------------------------------------------------------
# Wiring
# ----------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="paper-access",
        description=(
            "Retrieve the text of a list of papers and record honestly what arrived: "
            "JATS XML, an ASTA index probe, an open-access PDF, or an ask."
        ),
    )
    parser.add_argument("--version", action="version", version=__version__)
    subs = parser.add_subparsers(dest="command", required=True)

    def with_ids(sub: argparse.ArgumentParser) -> None:
        sub.add_argument("--id", action="append", help="An identifier (repeatable)")
        sub.add_argument("--input", help="A file with one identifier per line")

    p = subs.add_parser("resolve", help="Turn input into identifiers or candidates")
    with_ids(p)
    p.add_argument("--limit", type=int, default=5, help="Candidates per query (default 5)")
    p.set_defaults(func=cmd_resolve)

    p = subs.add_parser("fetch", help="Walk the waterfall")
    with_ids(p)
    p.add_argument("--store", required=True, help="Directory the papers live under")
    p.add_argument("--retry", action="store_true", help="Retry papers recorded as unreachable")
    p.add_argument("--no-pdf", action="store_true", help="Decline PDFs; XML only")
    p.add_argument("--no-asta", action="store_true", help="Skip the index probe")
    p.add_argument("--contact", help="Contact address for the open-access resolver")
    p.add_argument("--asta-key", help="ASTA API key (default: ASTA_API_KEY)")
    p.set_defaults(func=cmd_fetch)

    p = subs.add_parser("show", help="One paper's record, with any inconsistency flagged")
    p.add_argument("--store", required=True)
    p.add_argument("--id", required=True)
    p.set_defaults(func=cmd_show)

    p = subs.add_parser("report", help="The whole store as a table")
    p.add_argument("--store", required=True)
    p.add_argument("--json", action="store_true", help="JSON instead of the table")
    p.set_defaults(func=cmd_report)

    p = subs.add_parser("candidates", help="What in a drop zone could be a paper")
    p.add_argument("--inputs", required=True)
    p.set_defaults(func=cmd_candidates)

    p = subs.add_parser("adopt", help="Take in a supplied file as a paper")
    p.add_argument("--store", required=True)
    p.add_argument("--id", required=True)
    p.add_argument("--file", required=True)
    p.set_defaults(func=cmd_adopt)

    p = subs.add_parser("note", help="Set the record's one free-text field")
    p.add_argument("--store", required=True)
    p.add_argument("--id", required=True)
    p.add_argument("--text", required=True)
    p.set_defaults(func=cmd_note)

    p = subs.add_parser("verify", help="Re-resolve identifiers and re-check titles")
    p.add_argument("--store", required=True)
    p.set_defaults(func=cmd_verify)

    p = subs.add_parser("check", help="Validate a record file")
    p.add_argument("record")
    p.set_defaults(func=cmd_check)

    p = subs.add_parser("check-refs", help="Check a document's identifiers against a store")
    p.add_argument("document")
    p.add_argument("--store", required=True)
    p.set_defaults(func=cmd_check_refs)

    p = subs.add_parser("schema", help="Print the record schema")
    p.set_defaults(func=cmd_schema)

    p = subs.add_parser("papers", help="Identifiers in a store, one per line")
    p.add_argument("--store", required=True)
    p.set_defaults(func=cmd_papers)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return int(args.func(args))
    except PaperAccessError as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
