"""Gene tables: ``gene_ids.tsv.gz``, one row per gene of a dataset.

A table records, for each Ensembl gene of a dataset (an atlas's expression
matrix, say), its NCBIGene ID, official label, taxon and every name Translator
Name Resolver holds for it. :func:`build_gene_ids` makes one (network, rare);
:func:`load_gene_tables` loads one into SQLite for offline resolution.

The file format is the one evidencell commits under
``kb/taxonomy/{id}/gene_ids.tsv.gz``, so those files load here unchanged.
``stats_symbol`` and ``stats_col`` are the symbol the dataset itself uses and
the gene's position in it.
"""

from __future__ import annotations

import csv
import gzip
import io
import json
import sqlite3
import sys
import time
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from gene_identity import translator
from gene_identity.translator import normalise_name

GENE_IDS_COLUMNS = (
    "ensembl_id", "stats_symbol", "stats_col", "ncbi_gene_id", "label",
    "taxon", "equivalent_ids", "synonyms",
)

GENE_DDL = """\
CREATE TABLE IF NOT EXISTS genes (
  ensembl_id     TEXT PRIMARY KEY,
  stats_symbol   TEXT NOT NULL,
  stats_col      INTEGER NOT NULL,
  ncbi_gene_id   TEXT,
  label          TEXT,
  taxon          TEXT,
  symbol_norm    TEXT NOT NULL,
  label_norm     TEXT
);

CREATE TABLE IF NOT EXISTS gene_synonyms (
  ncbi_gene_id   TEXT NOT NULL,
  synonym        TEXT NOT NULL,
  synonym_norm   TEXT NOT NULL,
  source         TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_genes_ncbi        ON genes(ncbi_gene_id);
CREATE INDEX IF NOT EXISTS idx_genes_symbol      ON genes(stats_symbol);
CREATE INDEX IF NOT EXISTS idx_genes_symbol_norm ON genes(symbol_norm);
CREATE INDEX IF NOT EXISTS idx_genes_label_norm  ON genes(label_norm);
CREATE INDEX IF NOT EXISTS idx_gene_syn_norm     ON gene_synonyms(synonym_norm);
"""

_GENE_META_KEY = "gene_ids_meta"


def read_gene_ids(path: Path) -> tuple[dict[str, str], list[dict]]:
    """Read a ``gene_ids.tsv.gz``: ``(meta, rows)``.

    Meta lines precede the header as ``#key<TAB>value``. Row fields
    ``equivalent_ids`` / ``synonyms`` are ``|``-joined lists; ``stats_col``
    is an int; empty strings are None.
    """
    meta: dict[str, str] = {}
    body: list[str] = []
    with gzip.open(path, "rt", encoding="utf-8", newline="") as fh:
        lines = iter(fh)
        for ln in lines:
            if ln.startswith("#"):
                k, _, v = ln[1:].rstrip("\n").partition("\t")
                meta[k] = v
            else:
                body.append(ln)
                break
        body.extend(lines)
    rows: list[dict] = []
    for rec in csv.DictReader(io.StringIO("".join(body)), delimiter="\t"):
        row: dict[str, Any] = {k: (v or None) for k, v in rec.items()}
        row["stats_col"] = int(rec["stats_col"])
        row["equivalent_ids"] = rec["equivalent_ids"].split("|") if rec["equivalent_ids"] else []
        row["synonyms"] = rec["synonyms"].split("|") if rec["synonyms"] else []
        rows.append(row)
    return meta, rows


def write_gene_ids(path: Path, meta: Mapping[str, Any], rows: Iterable[Mapping]) -> None:
    """Write a ``gene_ids.tsv.gz`` deterministically (no mtime or filename in
    the gzip header), so a refresh that changes nothing produces no diff."""
    buf = io.StringIO()
    for k, v in meta.items():
        buf.write(f"#{k}\t{'' if v is None else v}\n")
    w = csv.writer(buf, delimiter="\t", lineterminator="\n")
    w.writerow(GENE_IDS_COLUMNS)
    for r in rows:
        w.writerow([
            r["ensembl_id"], r["stats_symbol"], r["stats_col"], r.get("ncbi_gene_id") or "",
            r.get("label") or "", r.get("taxon") or "",
            "|".join(r.get("equivalent_ids") or []),
            "|".join(s.replace("|", "/") for s in r.get("synonyms") or []),
        ])
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as raw, gzip.GzipFile(filename="", fileobj=raw, mode="wb", mtime=0) as gz:
        gz.write(buf.getvalue().encode("utf-8"))


def choose_stats_symbol(prior: str | None, label: str | None, synonyms: list[str]) -> str | None:
    """The symbol a gene goes by in the dataset.

    A prior symbol is kept when it is the current label or one of the gene's
    recorded names (a rename: ``Car8`` for Ca8, as older marker lists use).
    Otherwise the current label wins: a prior symbol the gene doesn't go by is
    a mapping error (``Np65`` for Ncam1) that exact-symbol matches would carry.
    """
    if not label:
        return prior
    if prior and (prior == label or normalise_name(prior) in {normalise_name(s) for s in synonyms}):
        return prior
    return label


def read_id_list(path: Path) -> list[tuple[str, str | None]]:
    """``(ensembl_id, prior_symbol)`` per line of a text file: an Ensembl ID,
    optionally followed by a tab and the symbol the dataset uses for it.
    Blank lines and ``#`` comments are skipped."""
    out: list[tuple[str, str | None]] = []
    for ln in path.read_text(encoding="utf-8").splitlines():
        ln = ln.strip()
        if not ln or ln.startswith("#"):
            continue
        ens, _, sym = ln.partition("\t")
        out.append((ens.strip(), sym.strip() or None))
    return out


def build_gene_ids(
    genes: list[tuple[str, str | None]],
    out_path: Path,
    *,
    meta: Mapping[str, Any] | None = None,
) -> Path:
    """Build a ``gene_ids.tsv.gz`` for Ensembl genes via NodeNormalization and
    Name Resolver (network).

    ``genes`` is ``(ensembl_id, prior_symbol)`` in dataset order. Versioned IDs
    (``ENSMUSG….5``) are stripped: NodeNorm resolves only the unversioned form.
    When ``out_path`` already exists its symbols count as prior symbols, so a
    refresh keeps them stable.
    """
    ensembl = [e.split(".", 1)[0] for e, _ in genes]
    prior = {e.split(".", 1)[0]: s for e, s in genes if s}
    if out_path.is_file():
        _, rows = read_gene_ids(out_path)
        prior.update({r["ensembl_id"]: r["stats_symbol"] for r in rows})
    print(f"  {len(ensembl):,} genes", file=sys.stderr)

    t0 = time.time()
    norm = translator.nodenorm([f"ENSEMBL:{e}" for e in ensembl])
    print(f"  NodeNorm: {time.time() - t0:.0f}s", file=sys.stderr)
    ncbi_ids = sorted({n["ncbi_gene_id"] for n in norm.values() if n and n.get("ncbi_gene_id")})
    t0 = time.time()
    syns = translator.nameres_synonyms(ncbi_ids)
    print(f"  Name Resolver synonyms for {len(ncbi_ids):,} genes: {time.time() - t0:.0f}s",
          file=sys.stderr)

    rows = []
    for col, ens in enumerate(ensembl):
        n = norm.get(f"ENSEMBL:{ens}") or {}
        ncbi = n.get("ncbi_gene_id")
        label = n.get("label")
        synonyms = syns.get(ncbi, []) if ncbi else []
        rows.append({
            "ensembl_id": ens,
            "stats_symbol": choose_stats_symbol(prior.get(ens), label, synonyms) or ens,
            "stats_col": col,
            "ncbi_gene_id": ncbi,
            "label": label,
            "taxon": n.get("taxon"),
            "equivalent_ids": n.get("equivalent_ids") or [],
            "synonyms": synonyms,
        })
    n_ncbi = sum(1 for r in rows if r["ncbi_gene_id"])
    header = {
        **(meta or {}),
        "fetched_at": datetime.now(UTC).isoformat(timespec="seconds"),
        **translator.translator_versions(),
        "n_genes": len(rows),
        "n_ncbi": n_ncbi,
    }
    write_gene_ids(out_path, header, rows)
    print(
        f"  Wrote {out_path}: {len(rows):,} genes, {n_ncbi:,} with NCBIGene "
        f"({100 * n_ncbi / max(1, len(rows)):.1f}%); the rest keep Ensembl as key",
        file=sys.stderr,
    )
    return out_path


def load_gene_tables(con: sqlite3.Connection, path: Path) -> int:
    """(Re)create and fill ``genes`` / ``gene_synonyms`` from a
    ``gene_ids.tsv.gz``. Returns the number of genes loaded (0 when the file
    doesn't exist)."""
    con.executescript("DROP TABLE IF EXISTS gene_synonyms; DROP TABLE IF EXISTS genes;")
    con.executescript(GENE_DDL)
    con.execute("CREATE TABLE IF NOT EXISTS _meta (key TEXT PRIMARY KEY, value TEXT)")
    con.execute("DELETE FROM _meta WHERE key = ?", (_GENE_META_KEY,))
    if not path.is_file():
        return 0
    meta, rows = read_gene_ids(path)
    con.executemany(
        "INSERT INTO genes VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (
                r["ensembl_id"], r["stats_symbol"], r["stats_col"], r["ncbi_gene_id"],
                r["label"], r["taxon"], normalise_name(r["stats_symbol"]),
                normalise_name(r["label"]) if r["label"] else None,
            )
            for r in rows
        ],
    )
    syn_rows = []
    for r in rows:
        if not r["ncbi_gene_id"]:
            continue
        for s in dict.fromkeys(r["synonyms"]):
            syn_rows.append((r["ncbi_gene_id"], s, normalise_name(s), "translator_nameres"))
    con.executemany("INSERT INTO gene_synonyms VALUES (?, ?, ?, ?)", syn_rows)
    con.execute("INSERT OR REPLACE INTO _meta VALUES (?, ?)", (_GENE_META_KEY, json.dumps(meta)))
    return len(rows)


def gene_ids_meta(con: sqlite3.Connection) -> dict[str, str] | None:
    """Provenance header of the loaded ``gene_ids.tsv.gz``, or None."""
    try:
        row = con.execute("SELECT value FROM _meta WHERE key = ?", (_GENE_META_KEY,)).fetchone()
    except sqlite3.OperationalError:
        return None
    return json.loads(row[0]) if row else None
