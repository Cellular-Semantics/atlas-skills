"""The test set: which CELLxGENE datasets are scored, and which are the default.

`full` is every dataset in the test set, in two tiers:

- ``n73`` -- the 74 datasets the published n=73 numbers and the frozen baseline
  were measured on. Frozen: it keeps its membership, including four CELLxGENE
  datasets it holds under two versions each, so those numbers stay comparable.
- ``l4`` -- every other CL_KG-curated dataset, one h5ad version per CELLxGENE
  dataset, added with the 2026-11 curation snapshot. Any other version the
  sheets name is kept as an ``alias``.

Running it all is slow and costs real money, so `subset` names a small, fixed,
hand-picked default -- see `data/subset.json` for what each case is there to
catch.
"""
from __future__ import annotations

import json

from .curation import DATA, parse_curation

MANIFEST_PATH = DATA / "manifest.json"
SUBSET_PATH = DATA / "subset.json"


#: The tiers of the test set, oldest first.
TIERS = ("n73", "l4")


def full(tier: str | None = None) -> dict[str, dict]:
    """Every dataset in the test set (or one tier), with its CDN URL and obs shape.

    Datasets whose obs could not be read at snapshot time carry ``n_cells:
    null``; they are kept, because silently dropping them would overstate
    coverage.
    """
    if tier is not None and tier not in TIERS:
        raise ValueError(f"Unknown tier {tier!r}; expected one of {list(TIERS)}")
    manifest = json.loads(MANIFEST_PATH.read_text())
    if tier is None:
        return manifest
    return {d: e for d, e in manifest.items() if e["tier"] == tier}


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
