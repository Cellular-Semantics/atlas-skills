"""How much of what can go wrong with a supplement manifest does the check catch?

The thing under test is ``paper-access supplements check``, the logic behind the
retrieve-supplements hook: the schema, the cross-rules, and the on-disk checks
(``record.check`` and ``supplements.check_on_disk``, called directly).

The clean store is real in the sense that matters: it is built from the
package's own record and supplement types, written to disk, and passes the check
before anything is mutated. Its mistakes are synthetic. Each class below is one
specific way a manifest or its files go wrong, applied one at a time to every
entry it can be applied to. So the rates measure the check against these
mutations. They do not measure how often a fetch really goes wrong in each way.

One class shows the check's limit rather than its reach. ``caption_swapped``
swaps two files' descriptions. Both are still real, sourced strings on real
files, so only a reader who opens the files can tell. The check is not meant to
catch it, and the expected rate is 0.

    python3 evals/paper-access/manifest_catch_rate.py            # the table, as markdown
    python3 evals/paper-access/manifest_catch_rate.py --json     # ... as JSON

Deterministic, offline, free. Needs ``paper-access`` installed.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import io
import json
import sys
import tempfile
import zipfile
from collections.abc import Callable
from pathlib import Path

from paper_access import record as record_module
from paper_access import store
from paper_access.ids import Identifier
from paper_access.record import Attempt, Availability, LocalSource, Metadata
from paper_access.supplements import (
    ArchiveMember,
    SupplementFile,
    SupplementRetrieval,
    Supplements,
    check_on_disk,
)

DOI = "10.1038/s41586-023-06812-z"
FILES = "supplements/files"
UNPACKED = "supplements/unpacked"


def _sha(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def _zip(entries: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, body in entries.items():
            archive.writestr(name, body)
    return buffer.getvalue()


def build_clean(root: Path) -> tuple[dict, Path]:
    """A store with one paper and a realistic manifest. Returns (record, paper dir)."""
    record = Availability(
        input=DOI,
        ids={"doi": Identifier.given(DOI)},
        route="europepmc",
        local_source=LocalSource(kind="jats", path="source/paper.jats.xml",
                                 sha256="a" * 64, bytes=42),
        metadata=Metadata(source_api="europepmc",
                          retrieved_at="2026-01-01T00:00:00+00:00", title="An atlas"),
        attempts=[Attempt("europepmc", "ok")],
        fetched_at="2026-01-01T00:00:00+00:00",
    )
    path = store.write(root, record)
    pdir = path.parent
    (pdir / FILES).mkdir(parents=True)
    (pdir / UNPACKED / "bundle.zip").mkdir(parents=True)

    table1 = b"cluster,gene,logfc\n1,GAD1,2.4\n2,SLC17A7,3.1\n"
    table2 = b"donor,age,sex\nD1,54,F\nD2,61,M\n"
    archive = _zip({"tables/deg.csv": b"gene,logfc\nA,1\n", "figs/f1.png": b"\x89PNG"})
    member = b"gene,logfc\nA,1\n"
    for name, body in (("table1.csv", table1), ("table2.csv", table2),
                       ("bundle.zip", archive)):
        (pdir / FILES / name).write_bytes(body)
    (pdir / UNPACKED / "bundle.zip" / "deg.csv").write_bytes(member)

    bundle = SupplementRetrieval(route="europepmc_bundle", retrieved_at="2026-01-01T00:00:00+00:00")
    supplements = Supplements(
        files=[
            SupplementFile(
                file_id="table1.csv", status="present", media_type="csv",
                label="Supplementary Table 1", description="Markers per cluster.",
                description_source="jats_caption", size_bytes=len(table1),
                sha256=_sha(table1), path=f"{FILES}/table1.csv", retrieval=bundle),
            SupplementFile(
                file_id="table2.csv", status="present", media_type="csv",
                label="Supplementary Table 2", description="Donor metadata.",
                description_source="jats_caption", size_bytes=len(table2),
                sha256=_sha(table2), path=f"{FILES}/table2.csv", retrieval=bundle),
            SupplementFile(
                file_id="bundle.zip", status="present", media_type="zip",
                size_bytes=len(archive), sha256=_sha(archive),
                path=f"{FILES}/bundle.zip", retrieval=bundle,
                members=[
                    ArchiveMember("tables/deg.csv", extracted=True, media_type="csv",
                                  size_bytes=len(member),
                                  path=f"{UNPACKED}/bundle.zip/deg.csv"),
                    ArchiveMember("figs/f1.png", extracted=False, media_type="png",
                                  note="figures are not wanted at any size"),
                ]),
            SupplementFile(
                file_id="figure1.png", status="skipped", media_type="png",
                retrieval=SupplementRetrieval(
                    route="none", note="figures are not wanted at any size")),
            SupplementFile(
                file_id="raw_counts.xlsx", status="deferred", media_type="xlsx",
                size_bytes=None, bytes_transferred=300_000_000,
                retrieval=SupplementRetrieval(
                    route="europepmc_bundle",
                    note="transfer abandoned past the 250 MB limit")),
            SupplementFile(
                file_id="table3.xlsx", status="missing", media_type="xlsx",
                retrieval=SupplementRetrieval(
                    route="europepmc_bundle", note="not in the bundle")),
            SupplementFile(file_id="table4.xlsx", status="listed", media_type="xlsx"),
        ],
        gaps=[
            {"what": "raw_counts.xlsx", "reason": "over the size threshold",
             "action": "re-run with --yes-large", "file_id": "raw_counts.xlsx"},
            {"what": "table3.xlsx", "reason": "not in the bundle",
             "action": "supply it with `supplements adopt`", "file_id": "table3.xlsx"},
        ],
        caption_source="jats",
        listed_at="2026-01-01T00:00:00+00:00",
        fetched_at="2026-01-01T00:00:00+00:00",
    )
    record.supplements = supplements
    return record.to_dict(), pdir


def problems(payload: dict, pdir: Path) -> list[str]:
    """What ``supplements check`` would report for one paper."""
    return record_module.check(payload) + check_on_disk(payload, pdir)


# ----------------------------------------------------------------------
# Mutations. Each takes (payload, paper dir, i) and applies itself to the i-th
# entry it can be applied to, returning False once there are no more.
# ----------------------------------------------------------------------

Mutation = Callable[[dict, Path, int], bool]


def _files(payload: dict, *statuses: str, has: str | None = None) -> list[dict]:
    return [f for f in payload["supplements"]["files"]
            if (not statuses or f["status"] in statuses) and (has is None or f.get(has))]


def _nth(items: list, i: int):
    return items[i] if i < len(items) else None


def delete_present_file(payload, pdir, i):
    """A stored file is gone from disk."""
    f = _nth(_files(payload, "present"), i)
    if f is None:
        return False
    (pdir / f["path"]).unlink()
    return True


def truncated(payload, pdir, i):
    """A stored file is shorter than recorded (an interrupted write)."""
    f = _nth(_files(payload, "present"), i)
    if f is None:
        return False
    target = pdir / f["path"]
    target.write_bytes(target.read_bytes()[:-2])
    return True


def flipped_byte(payload, pdir, i):
    """One byte changed, same size: only the digest can tell."""
    f = _nth(_files(payload, "present", has="sha256"), i)
    if f is None:
        return False
    target = pdir / f["path"]
    body = bytearray(target.read_bytes())
    body[0] ^= 0x01
    target.write_bytes(bytes(body))
    return True


def path_outside(payload, pdir, i):
    """The path points outside the paper directory, at a file that exists."""
    f = _nth(_files(payload, "present"), i)
    if f is None:
        return False
    outside = pdir.parent / "outside.bin"
    outside.write_bytes((pdir / f["path"]).read_bytes())
    f["path"] = "../outside.bin"
    return True


def present_without_path(payload, pdir, i):
    """Status present, no path."""
    f = _nth(_files(payload, "present"), i)
    if f is None:
        return False
    del f["path"]
    return True


def present_without_size(payload, pdir, i):
    """Status present, no size_bytes."""
    f = _nth(_files(payload, "present"), i)
    if f is None:
        return False
    del f["size_bytes"]
    return True


def _on_unfetched(field: str, value: str) -> Mutation:
    def mutate(payload, pdir, i):
        f = _nth(_files(payload, "listed", "missing", "skipped"), i)
        if f is None:
            return False
        f[field] = value
        return True
    return mutate


path_on_unfetched = _on_unfetched("path", f"{FILES}/table1.csv")
path_on_unfetched.__doc__ = "A stored path on a listed, missing or skipped file."
sha_on_unfetched = _on_unfetched("sha256", "b" * 64)
sha_on_unfetched.__doc__ = "A digest on a listed, missing or skipped file."


def deferred_no_gap(payload, pdir, i):
    """A deferred file with no gap saying what would fetch it."""
    f = _nth(_files(payload, "deferred"), i)
    if f is None:
        return False
    block = payload["supplements"]
    block["gaps"] = [g for g in block["gaps"] if g.get("file_id") != f["file_id"]]
    return True


def skipped_no_note(payload, pdir, i):
    """A skipped file with nothing saying why."""
    f = _nth(_files(payload, "skipped"), i)
    if f is None:
        return False
    f["retrieval"].pop("note", None)
    return True


def duplicate_file_id(payload, pdir, i):
    """The same file_id listed twice."""
    f = _nth(_files(payload), i)
    if f is None:
        return False
    payload["supplements"]["files"].append(copy.deepcopy(f))
    return True


def _members(payload) -> list[dict]:
    return [m for f in _files(payload) for m in f.get("members") or []]


def extracted_member_deleted(payload, pdir, i):
    """An extracted archive member is gone from disk."""
    m = _nth([m for m in _members(payload) if m.get("extracted")], i)
    if m is None:
        return False
    (pdir / m["path"]).unlink()
    return True


def extracted_without_path(payload, pdir, i):
    """extracted: true with nowhere stored."""
    m = _nth([m for m in _members(payload) if m.get("extracted")], i)
    if m is None:
        return False
    del m["path"]
    return True


def description_without_source(payload, pdir, i):
    """A description with no description_source."""
    f = _nth(_files(payload, has="description"), i)
    if f is None:
        return False
    del f["description_source"]
    return True


def invalid_status(payload, pdir, i):
    """A status outside the enum."""
    f = _nth(_files(payload), i)
    if f is None:
        return False
    f["status"] = "downloaded"
    return True


def stale_gap_on_present(payload, pdir, i):
    """A gap still asking for a file that is present."""
    f = _nth(_files(payload, "present"), i)
    if f is None:
        return False
    payload["supplements"]["gaps"].append(
        {"what": f["file_id"], "reason": "stale", "action": "fetch", "file_id": f["file_id"]})
    return True


def bytes_transferred_on_present(payload, pdir, i):
    """bytes_transferred left over from an abandoned attempt."""
    f = _nth(_files(payload, "present"), i)
    if f is None:
        return False
    f["bytes_transferred"] = 1000
    return True


def caption_swapped(payload, pdir, i):
    """Two files' descriptions swapped. Real, sourced, wrong: needs judgement."""
    if i:
        return False
    a, b = _files(payload, has="description")[:2]
    a["description"], b["description"] = b["description"], a["description"]
    return True


MUTATIONS: dict[str, Mutation] = {
    "delete_present_file": delete_present_file,
    "truncated": truncated,
    "flipped_byte": flipped_byte,
    "path_outside": path_outside,
    "present_without_path": present_without_path,
    "present_without_size": present_without_size,
    "path_on_unfetched": path_on_unfetched,
    "sha_on_unfetched": sha_on_unfetched,
    "deferred_no_gap": deferred_no_gap,
    "skipped_no_note": skipped_no_note,
    "duplicate_file_id": duplicate_file_id,
    "extracted_member_deleted": extracted_member_deleted,
    "extracted_without_path": extracted_without_path,
    "description_without_source": description_without_source,
    "invalid_status": invalid_status,
    "stale_gap_on_present": stale_gap_on_present,
    "bytes_transferred_on_present": bytes_transferred_on_present,
    "caption_swapped": caption_swapped,
}

#: The one class the check is not meant to catch.
NOT_CATCHABLE = {"caption_swapped"}


def measure() -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        clean, pdir = build_clean(Path(tmp) / "clean")
        result: dict = {"unmutated": {"problems": problems(clean, pdir)}, "mutations": {}}

    for name, mutate in MUTATIONS.items():
        applied = caught = 0
        i = 0
        while True:
            # A fresh store each time: a mutation may touch the disk.
            with tempfile.TemporaryDirectory() as tmp:
                payload, pdir = build_clean(Path(tmp) / "store")
                if not mutate(payload, pdir, i):
                    break
                applied += 1
                caught += bool(problems(payload, pdir))
            i += 1
        result["mutations"][name] = {
            "applied": applied,
            "caught": caught,
            "rate": round(caught / applied, 3) if applied else None,
            "catchable": name not in NOT_CATCHABLE,
            "what": (mutate.__doc__ or name).strip().splitlines()[0],
        }
    return result


def markdown(result: dict) -> str:
    found = result["unmutated"]["problems"]
    lines = [
        f"Unmutated: {'clean' if not found else str(len(found)) + ' problem(s)'}.",
        "",
        "| class | applied | caught | rate | meant to catch |",
        "|---|---|---|---|---|",
    ]
    for name, m in result["mutations"].items():
        rate = "—" if m["rate"] is None else f"{m['rate']:.0%}"
        lines.append(f"| `{name}` | {m['applied']} | {m['caught']} | {rate} | "
                     f"{'yes' if m['catchable'] else 'no'} |")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    result = measure()
    sys.stdout.write(json.dumps(result, indent=2) + "\n" if args.json else markdown(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
