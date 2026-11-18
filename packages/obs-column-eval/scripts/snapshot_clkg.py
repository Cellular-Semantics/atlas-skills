#!/usr/bin/env python3
"""Re-take the CL_KG curation snapshot that the gold set is read from.

    uv run --with openpyxl python3 packages/obs-column-eval/scripts/snapshot_clkg.py <CL_KG commit SHA>

Dev-only: not part of the wheel, and the package stays dependency-free. openpyxl
is needed only here, to turn the xlsx sheets into CSV once, at snapshot time.

What it does:

- lists ``anndata2rdf/src/curated_data`` in CL_KG **at the given commit**, so a
  snapshot names exactly what it copied;
- copies every CSV byte for byte, and writes each xlsx's curation sheet out as
  CSV (headers untouched -- ``parse_curation`` reads by header name);
- skips the files in ``EXCLUDED``, each with the reason it is not ground truth;
- writes ``data/curation/SOURCE.json`` recording the commit, the date, a hash
  of every file, and the exclusions. ``tests/test_gold_set.py`` holds the
  directory to that record, so a hand edit to a sheet fails the build: fixes
  belong in ``curation._CORRECTIONS``, where they are visible.

It replaces the whole directory. Review the diff before committing: an upstream
edit to a sheet the n73 tier is scored on shows up there, and the frozen
baseline test will say whether it moved a number.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

REPO = "Cellular-Semantics/CL_KG"
DIR = "anndata2rdf/src/curated_data"
OUT = Path(__file__).resolve().parent.parent / "src" / "obs_column_eval" / "data" / "curation"

#: Files in the upstream directory that are not ground truth, and why.
EXCLUDED = {
    "Curated_nlm-ckn_Datasets_Issue116.csv":
        "Generated with the author-annotation-columns plugin (0.4.3), not by hand. "
        "Scoring the plugin against its own output would be circular.",
    "README.md": "Not a curation sheet.",
}

#: Sheets inside an xlsx that are not the curation table.
SKIP_SHEETS = {"tracking"}


def _list(sha: str) -> list[str]:
    out = subprocess.run(
        ["gh", "api", f"repos/{REPO}/contents/{urllib.parse.quote(DIR)}?ref={sha}",
         "--jq", ".[].name"],
        capture_output=True, text=True, check=True)
    return [line for line in out.stdout.splitlines() if line]


def _fetch(sha: str, name: str) -> bytes:
    url = (f"https://raw.githubusercontent.com/{REPO}/{sha}/"
           f"{urllib.parse.quote(DIR + '/' + name)}")
    with urllib.request.urlopen(url, timeout=60) as resp:
        return resp.read()


def _xlsx_to_csv(data: bytes) -> tuple[str, str]:
    """The one curation sheet in a workbook, as CSV text, and its sheet name."""
    import openpyxl

    book = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    sheets = [ws for ws in book.worksheets if ws.title.strip().lower() not in SKIP_SHEETS]
    if len(sheets) != 1:
        raise SystemExit(f"expected one curation sheet, found {[ws.title for ws in sheets]}")
    ws = sheets[0]
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    for row in ws.iter_rows(values_only=True):
        cells = ["" if v is None else str(v) for v in row]
        while cells and cells[-1] == "":
            cells.pop()
        if cells:
            writer.writerow(cells)
    return buf.getvalue(), ws.title


def main() -> int:
    if len(sys.argv) != 2 or len(sys.argv[1]) != 40:
        sys.exit(__doc__.strip().splitlines()[2].strip())
    sha = sys.argv[1]

    names = _list(sha)
    unknown = [n for n in names if not n.endswith((".csv", ".xlsx")) and n not in EXCLUDED]
    if unknown:
        sys.exit(f"don't know how to read: {unknown}")

    for old in OUT.glob("*.csv"):
        old.unlink()

    files = {}
    for name in sorted(names):
        if name in EXCLUDED:
            continue
        data = _fetch(sha, name)
        entry = {"upstream": name, "upstream_sha256": hashlib.sha256(data).hexdigest()}
        if name.endswith(".xlsx"):
            text, sheet = _xlsx_to_csv(data)
            target = name[: -len(".xlsx")] + ".csv"
            data = text.encode("utf-8")
            entry["converted_from_xlsx"] = sheet
        else:
            target = name
        (OUT / target).write_bytes(data)
        entry["sha256"] = hashlib.sha256(data).hexdigest()
        files[target] = entry
        print(f"  {target}")

    (OUT / "SOURCE.json").write_text(json.dumps({
        "repo": f"https://github.com/{REPO}",
        "path": DIR,
        "commit": sha,
        "captured": time.strftime("%Y-%m-%d"),
        "how": "packages/obs-column-eval/scripts/snapshot_clkg.py",
        "excluded": {n: r for n, r in EXCLUDED.items() if n in names},
        "files": files,
    }, indent=2, ensure_ascii=False) + "\n")
    print(f"{len(files)} sheets -> {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
