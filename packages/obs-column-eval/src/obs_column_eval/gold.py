"""The gold set, keyed by dataset and field type.

Two sources feed one shape, ``{dsid: {field_type: [column, ...]}}``:

- **CL_KG curation** (``data/curation/``) supplies ``cell_type`` and nothing
  else. Its sheets record one distinction -- cell-type field or not -- so every
  non-cell-type column lands in an undifferentiated "other" bucket that mixes
  tissue, age, batch and QC. That makes it a source of *candidates*, never of
  tissue, stage or disease ground truth.
- **Hand curation** (``data/sample_fields/``) supplies the rest, one JSON file
  per dataset, each naming the columns for every field type it was curated for
  and carrying `notes` on the calls that were not obvious.

A dataset present in one source and absent from the other is normal. What is
*not* normal is treating silence as a negative, so each entry records which
field types it was curated for; scoring a field type against a dataset that was
never curated for it would manufacture false positives out of nothing.
"""
from __future__ import annotations

import json
from collections.abc import Mapping

from .curation import DATA, parse_curation
from .manifest import full

SAMPLE_FIELDS_DIR = DATA / "sample_fields"

#: Every field type the eval knows about.
#:
#: ``development_stage`` and ``other_stage`` are deliberately separate. Both are
#: stages and both are worth picking, but only the first resolves to HsapDv or
#: MmusDv: a menstrual phase is a cyclical property of an adult and a cell-cycle
#: phase is a per-cell computation. Collapsing them would hand a downstream
#: value mapper terms it cannot map and no way to tell.
FIELD_TYPES = ("cell_type", "tissue", "development_stage", "other_stage", "disease")


def sample_field_gold() -> dict[str, dict]:
    """The hand-curated entries, one per file, keyed by dataset id."""
    out = {}
    for path in sorted(SAMPLE_FIELDS_DIR.glob("*.json")):
        entry = json.loads(path.read_text())
        dsid = entry.get("dsid") or path.stem
        unknown = set(entry.get("columns", {})) - set(FIELD_TYPES)
        if unknown:
            raise ValueError(
                f"{path.name}: unknown field type(s) {sorted(unknown)}; "
                f"expected some of {list(FIELD_TYPES)}")
        out[dsid] = entry
    return out


def gold_set(field_types: tuple[str, ...] = FIELD_TYPES) -> dict[str, dict]:
    """Ground truth for the requested field types, per dataset.

    Each value is ``{"columns": {field_type: [...]}, "curated_for": [...]}``.
    ``curated_for`` is the honest part: it lists the field types this dataset
    was actually looked at for, so a scorer can skip the rest rather than score
    picks against an empty expectation.
    """
    unknown = set(field_types) - set(FIELD_TYPES)
    if unknown:
        raise ValueError(f"Unknown field type(s) {sorted(unknown)}; "
                         f"expected some of {list(FIELD_TYPES)}")

    out: dict[str, dict] = {}

    if "cell_type" in field_types:
        # Eligibility is the whole CL_KG sweep, not just the datasets with a
        # cell-type row in it. The curators looked at every dataset in the test
        # set; a dataset they recorded no cell-type field for is a real
        # expectation of "pick nothing", not a gap in coverage. Dropping those
        # would quietly change the denominator the frozen baseline was measured
        # against.
        curation = parse_curation()
        for dsid in set(curation) | set(full()):
            out[dsid] = {
                "columns": {"cell_type": list(
                    curation.get(dsid, {}).get("columns", []))},
                "curated_for": ["cell_type"],
                "source": "CL_KG curation"}

    for dsid, entry in sample_field_gold().items():
        cols = {ft: list(entry["columns"][ft])
                for ft in field_types if ft in entry.get("columns", {})}
        if not cols and dsid not in out:
            continue
        # A hand-curated entry is the more specific source: where it and CL_KG
        # both cover a field type, it wins.
        existing = out.setdefault(dsid, {"columns": {}, "curated_for": [],
                                         "source": "hand curation"})
        existing["columns"].update(cols)
        existing["curated_for"] = sorted(set(existing["curated_for"]) | set(cols))
        if cols and existing["source"] != "hand curation":
            existing["source"] = "CL_KG curation + hand curation"

    return out


def notes() -> dict[str, dict[str, str]]:
    """Per-dataset, per-column curation notes: the reasoning, not the answer.

    These are the calls worth arguing with -- why `Collection_site` is not a
    tissue, why `Tanner Stage` is a stage anyway. Read them before disputing a
    score.
    """
    return {dsid: entry.get("notes", {})
            for dsid, entry in sample_field_gold().items() if entry.get("notes")}


def flatten(picks: Mapping[str, Mapping[str, list[str]] | list[str]],
            field_type: str) -> dict[str, list[str]]:
    """One field type's picks out of a picks file, as ``{dsid: [column, ...]}``.

    A bare list is read as ``cell_type``: that is the shape every pre-existing
    picks file has, including the frozen n=73 baseline, and rewriting those to
    keep them scoreable would break the comparison they exist to provide.
    """
    out = {}
    for dsid, value in picks.items():
        if isinstance(value, Mapping):
            if field_type in value:
                out[dsid] = list(value[field_type])
        elif field_type == "cell_type":
            out[dsid] = list(value)
    return out
