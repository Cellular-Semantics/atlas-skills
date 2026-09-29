"""Per-column profiles of an obs table: kind, cardinality, and sample values.

This is the input an agent needs to decide *what a column is* -- whether it holds
author cell-type labels, a cluster index, a donor id or a QC score -- without
reading the column in full.

Two sources, one output shape:

- a **remote h5ad**, profiled over range reads. Only category tables and a
  bounded strided sample of each column are fetched, so the cost is close to
  ``--list-columns`` rather than a full obs read. Worth it only when obs itself
  is large; see the note in the skill.
- a **local table** already on disk (parquet/csv/tsv), which is free. If obs has
  already been pulled with ``h5ad-obs <url>``, profile that file rather than
  going back to the network -- on a mid-sized atlas a second remote pass costs
  more than the first one did.
"""
from __future__ import annotations

import time
from pathlib import Path

import h5py
import numpy as np
import pandas as pd

from .reader import (
    _ACTIVE,
    ObsReadError,
    ReadStats,
    _open,
    column_order,
    decode,
)

#: How many values to look at when estimating cardinality. Bounds the bytes
#: fetched per column; columns shorter than this are counted exactly.
DEFAULT_SCAN_N = 2000

#: How many of those values to show. Enough to tell a label from an index.
DEFAULT_SAMPLE_N = 20


def _spread(n: int, k: int) -> np.ndarray:
    """k row indices spread evenly across n rows, ascending and unique.

    Not the head. obs is very often sorted by donor, tissue or cluster, and the
    first 20 rows of a sorted column show one value -- which reads as a constant
    column when it is nothing of the kind. Spreading costs the same and does not
    lie.
    """
    if n <= k:
        return np.arange(n)
    return np.unique(np.linspace(0, n - 1, k).astype(np.int64))


def _take_spread(values: list, k: int) -> list:
    return [values[i] for i in _spread(len(values), k)]


def _values_to_python(values) -> list:
    """JSON-safe scalars, with NaN/NaT/None all collapsing to None."""
    out = []
    for v in values:
        if isinstance(v, bytes):
            out.append(v.decode(errors="replace"))
        elif v is None or v is pd.NaT or (isinstance(v, float) and v != v):
            out.append(None)
        # bool before int: numpy and python bools are both integer subtypes, and
        # a True that arrives as 1 changes what the column looks like.
        elif isinstance(v, (bool, np.bool_)):
            out.append(bool(v))
        elif isinstance(v, (int, np.integer)):
            out.append(int(v))
        elif isinstance(v, (float, np.floating)):
            out.append(float(v))
        elif isinstance(v, str):
            # np.str_ is a str subclass whose repr is `np.str_('x')`. Left alone
            # it renders that way in the text profile, which is noise the picker
            # has to see past.
            out.append(str(v))
        else:
            out.append(str(v))
    return out


def _summarise(name: str, kind: str, dtype: str, scanned: list, *,
               n_rows: int, n_scanned: int, sample_n: int,
               n_categories: int | None = None) -> dict:
    """Assemble one column's entry from the values actually looked at."""
    present = [v for v in scanned if v is not None]
    scanned_everything = n_scanned >= n_rows
    if n_categories is not None:
        # A category table is exact however few rows were sampled, so
        # cardinality is known for categoricals even on a 2M-row dataset.
        n_unique, estimated = n_categories, False
    else:
        n_unique, estimated = len(set(present)), not scanned_everything
    return {
        "name": name,
        "kind": kind,
        "dtype": dtype,
        "n_categories": n_categories,
        "n_unique": n_unique,
        "n_unique_estimated": estimated,
        "n_null": (n_scanned - len(present)) if scanned_everything else None,
        # A constant column carries no per-cell information. Claimable whenever
        # cardinality is *exact* -- which for a categorical is always, and for
        # anything else means every row was seen. Tying it to the scan instead
        # would leave the flag off for every dataset over `scan_n` rows, which
        # is most of them, and the picker's constant-column rule relies on it.
        # Conservative by design: a 2-category column using only one of them is
        # not flagged, because the categories are declared, not observed.
        "constant": bool(not estimated and n_unique <= 1),
        # Spread again, for the same reason the scan is spread: the head of a
        # sorted column is not a sample of it.
        "sample": _take_spread(_values_to_python(present or scanned), sample_n),
    }


def _profile_h5_column(obs, name: str, idx: np.ndarray, n_rows: int,
                       sample_n: int) -> dict:
    node = obs[name]
    if isinstance(node, h5py.Group):
        keys = set(node.keys())
        if {"categories", "codes"} <= keys:
            cats = list(decode(node["categories"][:]))
            codes = node["codes"][idx]
            scanned = [cats[c] if 0 <= c < len(cats) else None for c in codes]
            return _summarise(name, "categorical", str(node["codes"].dtype), scanned,
                              n_rows=n_rows, n_scanned=len(idx), sample_n=sample_n,
                              n_categories=len(cats))
        if {"values", "mask"} <= keys:
            values = list(node["values"][idx])
            mask = node["mask"][idx]
            scanned = [None if m else v for v, m in zip(values, mask, strict=True)]
            return _summarise(name, "nullable", str(node["values"].dtype), scanned,
                              n_rows=n_rows, n_scanned=len(idx), sample_n=sample_n)
        return {"name": name, "kind": "unknown", "dtype": None, "n_categories": None,
                "n_unique": None, "n_unique_estimated": None, "n_null": None,
                "constant": None, "sample": []}
    scanned = list(decode(node[idx]))
    kind = "string" if node.dtype.kind in ("S", "O", "U") else "array"
    return _summarise(name, kind, str(node.dtype), scanned,
                      n_rows=n_rows, n_scanned=len(idx), sample_n=sample_n)


def profile_remote(url: str, *, scan_n: int = DEFAULT_SCAN_N,
                   sample_n: int = DEFAULT_SAMPLE_N, block_size_mb: float = 2.0,
                   opener=None) -> tuple[dict, ReadStats]:
    """Profile obs in a remote h5ad without reading any column in full."""
    stats = ReadStats()
    _ACTIVE[0] = stats
    t0 = time.time()
    try:
        with h5py.File((opener or _open)(url, block_size_mb), "r") as h5:
            if "obs" not in h5:
                raise ObsReadError("No /obs group in this file -- is it really an h5ad?")
            obs = h5["obs"]
            names = column_order(obs)
            n_rows = _n_rows(obs, names)
            idx = _spread(n_rows, scan_n)
            columns = [_profile_h5_column(obs, n, idx, n_rows, sample_n) for n in names]
    finally:
        stats.seconds = time.time() - t0
        _ACTIVE[0] = None
    return _envelope(url, "remote-h5ad", n_rows, len(idx), columns), stats


def _n_rows(obs, names: list[str]) -> int:
    if "_index" in obs:
        return int(obs["_index"].shape[0])
    for n in names:
        node = obs[n]
        if isinstance(node, h5py.Group):
            for key in ("codes", "values"):
                if key in node:
                    return int(node[key].shape[0])
        else:
            return int(node.shape[0])
    raise ObsReadError("obs has no readable columns; cannot determine cell count.")


def profile_frame(df: pd.DataFrame, *, source: str = "<dataframe>",
                  scan_n: int = DEFAULT_SCAN_N,
                  sample_n: int = DEFAULT_SAMPLE_N) -> dict:
    """Profile an obs table already in memory. No network, no sampling limits
    beyond `scan_n`, which is kept so the output matches the remote path."""
    n_rows = int(df.shape[0])
    idx = _spread(n_rows, scan_n)
    columns = []
    for name in df.columns:
        series = df[name]
        taken = series.iloc[idx]
        if isinstance(series.dtype, pd.CategoricalDtype):
            columns.append(_summarise(
                str(name), "categorical", str(series.dtype.categories.dtype),
                _values_to_python(taken.tolist()), n_rows=n_rows, n_scanned=len(idx),
                sample_n=sample_n, n_categories=len(series.dtype.categories)))
            continue
        kind = "string" if series.dtype == object else "array"
        columns.append(_summarise(str(name), kind, str(series.dtype),
                                  _values_to_python(taken.tolist()), n_rows=n_rows,
                                  n_scanned=len(idx), sample_n=sample_n))
    return _envelope(source, "local-table", n_rows, len(idx), columns)


def profile_local(path: str | Path, **kwargs) -> dict:
    """Profile an obs table on disk. Format is taken from the suffix."""
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix == ".parquet":
        df = pd.read_parquet(path)
    elif suffix in (".csv", ".tsv", ".txt"):
        df = pd.read_csv(path, sep="\t" if suffix == ".tsv" else ",", index_col=0,
                         low_memory=False)
    else:
        raise ObsReadError(
            f"Don't know how to read {path.name}: expected .parquet, .csv or .tsv. "
            "A remote h5ad needs a URL, not a path.")
    return profile_frame(df, source=str(path), **kwargs)


def _envelope(source: str, source_kind: str, n_rows: int, n_scanned: int,
              columns: list[dict]) -> dict:
    return {
        "source": source,
        "source_kind": source_kind,
        "n_rows": n_rows,
        "n_scanned": n_scanned,
        "n_columns": len(columns),
        "columns": columns,
    }


def as_text(prof: dict, *, sample_n: int = 10) -> str:
    """The profile as a table. This is what an agent reads.

    Deliberately only data -- no instructions about what to pick. The judgment
    lives in the skill and the picker agent, in one place, so the two cannot
    drift apart.
    """
    lines = [
        f"obs profile: {prof['source']}",
        f"{prof['n_rows']} rows x {prof['n_columns']} columns; "
        f"{prof['n_scanned']} rows scanned per column.",
        "",
        "name | kind | n_unique | sample values",
    ]
    for col in prof["columns"]:
        if col["kind"] == "categorical":
            kind = f"categorical[{col['n_categories']} cats]"
        elif col["kind"] == "unknown":
            kind = "unknown encoding"
        else:
            kind = f"{col['kind']} {col['dtype']}"
        nu = col["n_unique"]
        nu = "?" if nu is None else (f"~{nu}" if col["n_unique_estimated"] else str(nu))
        if col["constant"]:
            nu += " (constant)"
        sample = col["sample"][:sample_n]
        preview = ", ".join(repr(v) for v in sample)
        if len(col["sample"]) > sample_n:
            preview += ", ..."
        lines.append(f"{col['name']} | {kind} | {nu} | {preview}")
    return "\n".join(lines)
