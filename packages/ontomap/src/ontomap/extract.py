"""Pull the declared columns out of a sample table. Interpret nothing.

The one job here is to produce, for every sample, the author's strings exactly
as written, with units folded in from their sibling columns and a scope flag
attached. Anything that looks like a judgement at this layer is a judgement made
before the evidence was assembled.
"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

from .config import Config
from .errors import OntomapError


def read_table(path: str | Path) -> list[dict[str, Any]]:
    """CSV or TSV by extension; parquet if pyarrow is installed."""
    path = Path(path)
    if path.suffix.lower() in {".csv", ".tsv"}:
        delimiter = "\t" if path.suffix.lower() == ".tsv" else ","
        with path.open(newline="", encoding="utf-8-sig") as handle:
            return list(csv.DictReader(handle, delimiter=delimiter))
    if path.suffix.lower() in {".parquet", ".pq"}:
        try:
            import pyarrow.parquet as pq
        except ImportError as exc:
            raise OntomapError(
                "reading parquet needs the 'tables' extra: pip install 'ontomap[tables]'"
            ) from exc
        return pq.read_table(path).to_pylist()
    raise OntomapError(f"unsupported table format: {path.suffix!r}")


def extract(rows: list[dict[str, Any]], config: Config) -> list[dict[str, Any]]:
    """One record per sample: raw strings per source column, plus scope."""
    missing = {c for c in config.columns() if rows and c not in rows[0]}
    if missing:
        raise OntomapError(
            f"declared column(s) not in the table: {sorted(missing)}. "
            f"Available: {sorted(rows[0])[:20]}"
        )
    out = []
    for position, row in enumerate(rows):
        in_scope = config.scope_filter.admits(row) if config.scope_filter else True
        record: dict[str, Any] = {
            "row": position,
            "scope": "in_scope" if in_scope else "out_of_scope",
            "raw": {},
        }
        for name, sources in config.fields.items():
            record["raw"][name] = [
                {
                    "column": source.column,
                    "role": source.role,
                    # Verbatim. Never edited, never stripped of anything the
                    # author wrote -- the mapped columns carry interpretation,
                    # this one carries the record.
                    "value": _text(row.get(source.column)),
                    "unit": _text(row.get(source.unit_column)) if source.unit_column else None,
                    "frame": source.frame,
                }
                for source in sources
            ]
        out.append(record)
    return out


def _text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def distinct_values(records: list[dict[str, Any]], field_name: str) -> dict[str, int]:
    """Distinct raw strings for a field, with sample counts.

    Effort should follow the cells: a string on 4,000 samples deserves more of a
    curator's attention than one on three, and the pipeline maps distinct values
    rather than rows anyway.
    """
    counts: dict[str, int] = {}
    for record in records:
        for source in record["raw"].get(field_name, []):
            value = source["value"]
            if value:
                counts[value] = counts.get(value, 0) + 1
    return dict(sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])))
