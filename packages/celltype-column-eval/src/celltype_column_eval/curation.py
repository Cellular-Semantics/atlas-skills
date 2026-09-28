"""CL_KG hand curation -> per-dataset ground truth.

The curation sheets list, per CELLxGENE dataset, which author obs columns hold
which kind of content. Only the cell-type rows are ground truth here: the sheets
also record BCR/TCR clonotypes, donor demographics and sample identifiers as
"author categories", and counting those as cell-type columns inflates the
denominator with things no picker should ever pick.

The sheets are a **snapshot**, taken once and frozen with the package. They are
the gold set, so they must not move underneath a score.
"""
from __future__ import annotations

import csv
import re
from collections import defaultdict
from pathlib import Path

DATA = Path(__file__).parent / "data"
CURATION_DIR = DATA / "curation"

UUID_RE = re.compile(r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})")

#: Values of the sheets' `Content` column that mean "this row names a cell-type
#: field". Everything else is a different kind of author category.
CELL_TYPE_CONTENT = {
    "cell types",
    "cell type",
    "cell type and infection source",
}

_NULLISH = {"n/a", "na", "none", "-", ""}


def parse_curation(curation_dir: str | Path | None = None, *,
                   filter_celltype: bool = True) -> dict[str, dict]:
    """Parse the curation sheets into ``{dataset_id: {...}}``.

    Parameters
    ----------
    curation_dir:
        Directory of curation CSVs. Defaults to the snapshot shipped in the
        package, which is what any published score must be against.
    filter_celltype:
        Keep only rows whose ``Content`` names a cell-type field. Turning this
        off gives the full author-category set, which is a different question
        and not comparable to any number in the docs.

    Returns
    -------
    ``{dataset_id: {"groups": [...], "columns": [...], "rows": int}}`` --
    ``columns`` being the curated cell-type column names for that dataset.
    """
    curation_dir = Path(curation_dir) if curation_dir else CURATION_DIR
    by_dataset: dict[str, dict] = defaultdict(
        lambda: {"groups": set(), "columns": set(), "rows": 0})

    for path in sorted(curation_dir.glob("*.csv")):
        group = path.stem
        with path.open(newline="", encoding="utf-8") as fh:
            for raw in csv.DictReader(fh):
                row = {(k.strip() if k else k): (v.strip() if isinstance(v, str) else v)
                       for k, v in raw.items()}
                if filter_celltype and \
                        (row.get("Content") or "").lower() not in CELL_TYPE_CONTENT:
                    continue
                match = UUID_RE.search(row.get("h5ad link", ""))
                if not match:
                    continue
                col = row.get("Author Category Cell Type Field Name") or ""
                if col.lower() in _NULLISH:
                    continue
                entry = by_dataset[match.group(1)]
                entry["groups"].add(group)
                entry["columns"].add(col)
                entry["rows"] += 1

    return {dsid: {"groups": sorted(v["groups"]), "columns": sorted(v["columns"]),
                   "rows": v["rows"]}
            for dsid, v in by_dataset.items()}
