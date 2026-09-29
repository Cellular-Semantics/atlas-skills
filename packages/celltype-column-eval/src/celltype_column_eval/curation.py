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

#: Transcription fixes, applied on read so the shipped CSVs stay a faithful copy
#: of the CL_KG sheets. These four name columns that do not exist in the
#: dataset's obs -- the curator capitalised them. obs column names are
#: case-sensitive, so scoring against the sheet as written marks a picker wrong
#: for choosing the column that is actually there.
#:
#: Found by cross-checking all 186 curated names against the committed obs
#: profiles; these were the only mismatches, and `evals/test_cases.py` fails if
#: another appears. Case is NOT folded during scoring -- an agent inventing a
#: name with the wrong case would fail at pull time, and that is a real error
#: worth catching.
_CORRECTIONS: dict[str, dict[str, str]] = {
    "ac818189-5c6b-48d2-8bf1-f7511de7b5a9": {
        "Cell_type_original": "cell_type_original",
        "Cell_type_source": "cell_type_source",
        "Cluster": "cluster",
        "Cluster_source": "cluster_source",
    },
}


#: Cell-type columns the sheets do not list but that demonstrably hold author
#: cell-type labels, accepted in review on 2026-09-29 (see
#: docs/curation-review-2026-09-29.md, sections 2.1 and 2.2). Applied on read for
#: the same reason as _CORRECTIONS: the CSVs stay a faithful copy of the CL_KG
#: sheets, and the delta from upstream is visible in one place rather than
#: buried in a diff of ten spreadsheets.
#:
#: Every name here is checked against the committed obs profiles by
#: `evals/test_cases.py`, so an addition that names a nonexistent column fails
#: the build rather than silently capping that dataset's score.
#:
#: NOT added, and still open: `scanvi_label` and `transf_ann_level_*` on the two
#: HLCA datasets are model predictions rather than author assertions, and want a
#: `Content` value of their own -- section 3.2 of the review.
_HLCA_PRE_HARMONISATION = [
    "ann_coarse_for_GWAS_and_modeling",
    "original_ann_level_1",
    "original_ann_level_2",
    "original_ann_level_3",
    "original_ann_level_4",
    "original_ann_level_5",
    "original_ann_nonharmonized",
]

_ADDITIONS: dict[str, list[str]] = {
    # HLCA-derived lung atlases: the sheets curate the harmonised ann_level_*
    # hierarchy but not the contributing studies' own annotations, which are
    # arguably the more "author-provided" of the two.
    "b13072bd-9cb6-42ca-9f4f-01252baef273": _HLCA_PRE_HARMONISATION,
    "b351804c-293e-4aeb-9c4c-043db67f4540": _HLCA_PRE_HARMONISATION,
    # An author-asserted CL label (47 values: 'serous secreting cell', 'mast
    # cell'), distinct from the portal's cell_type_ontology_term_id.
    "443f7fb8-2a27-47c3-98f6-6a603c7a294e": ["putative_CL_label"],
}


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
                dsid = match.group(1)
                col = _CORRECTIONS.get(dsid, {}).get(col, col)
                entry = by_dataset[dsid]
                entry["groups"].add(group)
                entry["columns"].add(col)
                entry["rows"] += 1

    if filter_celltype:
        for dsid, extra in _ADDITIONS.items():
            if dsid in by_dataset:
                by_dataset[dsid]["columns"].update(extra)

    return {dsid: {"groups": sorted(v["groups"]), "columns": sorted(v["columns"]),
                   "rows": v["rows"]}
            for dsid, v in by_dataset.items()}
