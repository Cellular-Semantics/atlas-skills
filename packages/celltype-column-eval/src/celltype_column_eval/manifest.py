"""The test set: which CELLxGENE datasets are scored, and which are the default.

`full` is all 74 datasets the curation covers. Running it is slow and costs real
money, so `subset` names a small, fixed, hand-picked default -- see
`data/subset.json` for what each case is there to catch.
"""
from __future__ import annotations

import json

from .curation import DATA, parse_curation

MANIFEST_PATH = DATA / "manifest.json"
SUBSET_PATH = DATA / "subset.json"


def full() -> dict[str, dict]:
    """Every dataset in the test set, with its CDN URL and obs shape.

    Datasets whose obs could not be read at snapshot time carry ``n_cells:
    null``; they are kept, because silently dropping them would overstate
    coverage.
    """
    return json.loads(MANIFEST_PATH.read_text())


def subset() -> dict[str, dict]:
    """The default eval set: a handful of datasets, each with a stated reason."""
    return json.loads(SUBSET_PATH.read_text())


def with_ground_truth(datasets: dict[str, dict] | None = None) -> dict[str, dict]:
    """Manifest entries joined to their curated cell-type columns.

    Datasets the curation does not cover as cell-type rows get ``curated: []``
    -- a legitimate expectation (pick nothing), not missing data.
    """
    datasets = full() if datasets is None else datasets
    curation = parse_curation()
    return {dsid: {**entry, "curated": curation.get(dsid, {}).get("columns", [])}
            for dsid, entry in datasets.items()}
