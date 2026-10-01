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
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from . import __version__, refs, supp_flow, waterfall
from . import record as record_module
from .errors import PaperAccessError
from .store import read as read_record
from .store import read_all, write_or_note
from .store import write as write_record


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
# Supplementary material
# ----------------------------------------------------------------------


def _supp_targets(args: argparse.Namespace) -> list[str]:
    """Which papers a supplements command was asked about.

    A corpus is the actual use case, and before this the commands took a single
    `--id` while `paper-access fetch` already took a list — so every sweep was
    a hand-rolled shell loop, which is where the concurrency and the timeouts
    went missing.
    """
    if getattr(args, "all", False):
        out = []
        for found in read_all(args.store):
            try:
                _, value = found.primary_id
            except PaperAccessError:
                continue
            out.append(value)
        if not out:
            raise PaperAccessError(f"no papers in {args.store}")
        return out
    ids: list[str] = list(getattr(args, "id", None) or [])
    if getattr(args, "input", None):
        path = Path(args.input)
        if not path.is_file():
            raise PaperAccessError(f"no such file: {path}")
        for line in path.read_text(encoding="utf-8").splitlines():
            text = line.strip()
            if text and not text.startswith("#"):
                ids.append(text)
    if not ids:
        raise PaperAccessError("nothing to do: pass --id, --input or --all")
    return ids


def _sweep(args: argparse.Namespace, work) -> int:
    """Run one job per paper, concurrently, and report per paper.

    Exit codes are about the sweep rather than about one paper: 0 when every
    paper was attempted and nothing is waiting on a decision, 2 when something
    needs one, 1 when a paper errored outright. A sweep that stopped on the
    first large bundle would be worse than one that capped.
    """
    targets = _supp_targets(args)
    workers = max(1, min(getattr(args, "concurrency", 1) or 1, len(targets)))
    results: dict[str, Any] = {}

    def run_one(identifier: str) -> tuple[str, dict[str, Any]]:
        try:
            return identifier, work(identifier)
        except PaperAccessError as exc:
            return identifier, {"error": str(exc)}

    if workers == 1:
        rows = [run_one(i) for i in targets]
    else:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            rows = list(pool.map(run_one, targets))
    for identifier, payload in rows:
        results[identifier] = payload

    errored = [i for i, r in results.items() if r.get("error")]
    needs_decision = [
        i for i, r in results.items()
        if any(f.get("status") == "deferred" for f in (r.get("files") or []))
    ]
    _emit({
        "papers": results,
        "summary": {
            "attempted": len(targets),
            "errored": errored,
            "needs_decision": needs_decision,
        },
    })
    if errored:
        return 1
    if needs_decision and not getattr(args, "skip_large", False):
        return 2
    return 0


def _needs_record(args: argparse.Namespace, identifier: str | None = None):
    found = read_record(args.store, identifier or args.id)
    if found is None:
        raise PaperAccessError(
            f"no record for {identifier or args.id} in {args.store}; fetch the paper "
            "first — the article XML is where the supplement filenames and captions live"
        )
    return found


def cmd_supp_list(args: argparse.Namespace) -> int:
    def work(identifier: str) -> dict[str, Any]:
        record = _needs_record(args, identifier)
        record.supplements = supp_flow.list_supplements(
            record, args.store, asta_key=args.asta_key
        )
        _, note = write_or_note(args.store, record)
        payload = record.supplements.to_dict()
        if note:
            payload["write_problem"] = note
        return payload

    return _sweep(args, work)


def cmd_supp_fetch(args: argparse.Namespace) -> int:
    def work(identifier: str) -> dict[str, Any]:
        record = _needs_record(args, identifier)
        if record.supplements is None or not record.supplements.files:
            record.supplements = supp_flow.list_supplements(
                record, args.store, asta_key=args.asta_key
            )
        record.supplements = supp_flow.fetch_supplements(
            record,
            args.store,
            retry=args.retry,
            use_bundle=not args.no_bundle,
            large_bytes=args.large_bytes,
            max_bytes=args.max_bundle_bytes,
            allow_large=args.yes_large,
            skip_large=args.skip_large,
            include_media=args.include_media,
            file_timeout=args.file_timeout,
            paper_timeout=args.paper_timeout,
        )
        # A record that will not validate is written anyway with the problems
        # noted, so one bad file cannot strand the paper for every later run.
        _, note = write_or_note(args.store, record)
        payload = record.supplements.to_dict()
        if note:
            payload["write_problem"] = note
        return payload

    return _sweep(args, work)


def cmd_supp_unpack(args: argparse.Namespace) -> int:
    def work(identifier: str) -> dict[str, Any]:
        record = _needs_record(args, identifier)
        record.supplements = supp_flow.unpack(record, args.store)
        _, note = write_or_note(args.store, record)
        payload = record.supplements.to_dict()
        if note:
            payload["write_problem"] = note
        return payload

    return _sweep(args, work)


def cmd_migrate(args: argparse.Namespace) -> int:
    """Bring every record in a store up to the current schema, without fetching.

    Reading tolerates an older version, so this is only needed to stop the
    upgrade happening lazily one paper at a time — but it is what makes a
    schema bump something other than "re-fetch your whole corpus".
    """
    from .record import SCHEMA_VERSION

    changed, failed = [], []
    for path in sorted(Path(args.store).glob("*/availability.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            failed.append({"path": str(path), "error": str(exc)})
            continue
        was = payload.get("schema_version")
        if was == SCHEMA_VERSION:
            continue
        try:
            record = record_module.Availability.from_dict(payload)
            write_record(args.store, record)
        except PaperAccessError as exc:
            failed.append({"path": str(path), "from": was, "error": str(exc)})
            continue
        changed.append({"path": str(path), "from": was, "to": SCHEMA_VERSION})
    _emit({"migrated": changed, "failed": failed, "schema_version": SCHEMA_VERSION})
    return 1 if failed else 0


def cmd_supp_adopt(args: argparse.Namespace) -> int:
    record = _needs_record(args)
    record.supplements, unmatched = supp_flow.adopt(record, args.store, args.incoming)
    write_record(args.store, record)
    _emit({"supplements": record.supplements.to_dict(), "unmatched": unmatched})
    return 0


def cmd_supp_show(args: argparse.Namespace) -> int:
    record = _needs_record(args)
    if record.supplements is None:
        _emit({"error": f"nothing recorded about supplements for {args.id}"})
        return 1
    payload = record.to_dict()
    problems = record_module.check(payload)
    _emit({"supplements": payload["supplements"], "problems": problems})
    return 2 if problems else 0


def cmd_supp_report(args: argparse.Namespace) -> int:
    rows = []
    for record in read_all(args.store):
        try:
            _, value = record.primary_id
        except PaperAccessError:
            continue
        found = record.supplements
        row = {"id": value, "listed": 0, "present": 0, "deferred": 0, "missing": 0}
        if found is None:
            row["status"] = "not looked at"
        else:
            row.update(found.counts)
            row["status"] = "looked at"
            row["gaps"] = len(found.gaps)
        rows.append(row)
    if args.json:
        _emit({"papers": rows})
        return 0
    _print_supp_report(rows)
    return 0


def _print_supp_report(rows: list[dict[str, Any]]) -> None:
    if not rows:
        print("no papers in this store")
        return
    width = max(len(str(r["id"])) for r in rows)
    print(f"{'id'.ljust(width)}  present  listed  deferred  missing  gaps")
    for row in rows:
        print(
            f"{str(row['id']).ljust(width)}  "
            f"{row.get('present', 0):>7}  "
            f"{row.get('listed', 0):>6}  "
            f"{row.get('deferred', 0):>8}  "
            f"{row.get('missing', 0):>7}  "
            f"{row.get('gaps', 0):>4}"
        )
    unlooked = [r for r in rows if r.get("status") == "not looked at"]
    if unlooked:
        print(
            f"\n{len(unlooked)} paper(s) have not been looked at, which is not the "
            "same as having no supplements:"
        )
        for row in unlooked:
            print(f"  {row['id']}")
    deferred = [r for r in rows if r.get("deferred")]
    if deferred:
        print(
            f"\n{len(deferred)} paper(s) have files nobody has agreed to download yet. "
            "Nothing was learnt about whether they can be got:"
        )
        for row in deferred:
            print(f"  {row['id']}: {row['deferred']} file(s) — see `supplements show`")


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

    p = subs.add_parser(
        "migrate", help="Bring a store's records up to the current schema"
    )
    p.add_argument("--store", required=True)
    p.set_defaults(func=cmd_migrate)

    p = subs.add_parser("papers", help="Identifiers in a store, one per line")
    p.add_argument("--store", required=True)
    p.set_defaults(func=cmd_papers)

    supp = subs.add_parser(
        "supplements", help="A paper's supplementary material: list, fetch, unpack"
    ).add_subparsers(dest="supp_command", required=True)

    def with_store_id(sub: argparse.ArgumentParser) -> None:
        """Store plus a set of papers: one, a file of them, or all of them."""
        sub.add_argument("--store", required=True)
        sub.add_argument("--id", action="append", help="An identifier (repeatable)")
        sub.add_argument("--input", help="A file with one identifier per line")
        sub.add_argument("--all", action="store_true",
                         help="Every paper in the store")
        sub.add_argument("--concurrency", type=int, default=4,
                         help="Papers at a time (default 4)")

    s = supp.add_parser("list", help="What supplementary files this paper has")
    with_store_id(s)
    s.add_argument("--asta-key", help="ASTA API key (default: ASTA_API_KEY)")
    s.set_defaults(func=cmd_supp_list)

    s = supp.add_parser("fetch", help="Fetch the listed files")
    with_store_id(s)
    s.add_argument("--retry", action="store_true",
                   help="Try again for files recorded as missing or deferred")
    s.add_argument("--include-media", action="store_true",
                   help="Fetch figures and video too; off by default at any size")
    s.add_argument("--file-timeout", type=float, default=supp_flow.DEFAULT_FILE_TIMEOUT,
                   help="Wall-clock seconds for one file (default 120)")
    s.add_argument("--paper-timeout", type=float, default=supp_flow.DEFAULT_PAPER_TIMEOUT,
                   help="Wall-clock seconds for one paper (default 600)")
    s.add_argument("--no-bundle", action="store_true",
                   help="Skip the Europe PMC bundle route")
    s.add_argument("--large-bytes", type=int, default=supp_flow.DEFAULT_LARGE_BYTES,
                   help="Defer a download over this size (default 50 MB)")
    s.add_argument("--max-bundle-bytes", type=int, default=supp_flow.DEFAULT_MAX_BYTES,
                   help="Never exceed this, even with --yes-large")
    s.add_argument("--yes-large", action="store_true",
                   help="Proceed with a download over --large-bytes")
    s.add_argument("--skip-large", action="store_true",
                   help="Record the deferral and exit 0, so a batch keeps going")
    s.add_argument("--asta-key", help="ASTA API key (default: ASTA_API_KEY)")
    s.set_defaults(func=cmd_supp_fetch)

    s = supp.add_parser("unpack", help="Expand stored archives, recording members")
    with_store_id(s)
    s.set_defaults(func=cmd_supp_unpack)

    s = supp.add_parser("adopt", help="Take in files a person dropped")
    s.add_argument("--store", required=True)
    s.add_argument("--id", required=True)
    s.add_argument("--incoming", required=True)
    s.set_defaults(func=cmd_supp_adopt)

    s = supp.add_parser("show", help="One paper's supplements, with problems flagged")
    s.add_argument("--store", required=True)
    s.add_argument("--id", required=True)
    s.set_defaults(func=cmd_supp_show)

    s = supp.add_parser("report", help="Supplement coverage across the store")
    s.add_argument("--store", required=True)
    s.add_argument("--json", action="store_true")
    s.set_defaults(func=cmd_supp_report)

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
