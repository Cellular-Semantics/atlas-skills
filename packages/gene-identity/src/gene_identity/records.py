"""The skill's output records: load a ``.gene-records.json`` and validate it
against ``gene_record.schema.json``.

Shape only. Whether an ID exists, belongs to the taxon and carries that
official symbol needs a lookup and is not checked here.
"""

from __future__ import annotations

import json
from importlib import resources
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

RECORDS_SUFFIX = ".gene-records.json"


def schema() -> dict:
    return json.loads(
        resources.files("gene_identity").joinpath("schemas/gene_record.schema.json").read_text()
    )


def _where(records: Any, path: list) -> str:
    """``[2] (SOM).kind`` for an error at ``records[2]['kind']``."""
    if not path:
        return "(file)"
    i, rest = path[0], path[1:]
    label = f"[{i}]"
    if isinstance(i, int) and isinstance(records, list) and i < len(records):
        rec = records[i]
        if isinstance(rec, dict) and isinstance(rec.get("name"), str):
            label += f" ({rec['name']})"
    return label + "".join(f"[{p}]" if isinstance(p, int) else f".{p}" for p in rest)


def _message(err) -> str:
    """One readable line per error: the per-outcome rules are if/then
    branches, whose raw messages ("None was expected") don't say why."""
    v = err.validator
    if v == "const" and err.validator_value is None:
        return f"must be null or absent for this outcome (got {err.instance!r})"
    if v == "maxItems" and err.validator_value == 0:
        return "must be empty unless the record is UNRESOLVED with kind AMBIGUOUS"
    if v == "minItems":
        return "AMBIGUOUS needs the claimant genes: at least two"
    if v == "required":
        # Per-outcome rules live under allOf; the always-required fields don't.
        per_outcome = "allOf" in err.absolute_schema_path
        return err.message.replace(
            "is a required property", "is required for this outcome" if per_outcome else "is required"
        )
    return err.message


def validate(records: Any) -> list[str]:
    """Schema problems, one line each, in document order. Empty when valid."""
    validator = Draft202012Validator(schema())
    # Document order: record 2 before record 10.
    errors = sorted(validator.iter_errors(records), key=lambda e: [
        (0, p, "") if isinstance(p, int) else (1, 0, str(p)) for p in e.absolute_path
    ])
    seen: set[str] = set()
    out: list[str] = []
    for e in errors:
        line = f"{_where(records, list(e.absolute_path))}: {_message(e)}"
        if line not in seen:
            seen.add(line)
            out.append(line)
    return out


def load(path: Path) -> Any:
    """Parse a records file. Raises ``ValueError`` on bad JSON."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"{path}: not JSON ({exc})") from exc
