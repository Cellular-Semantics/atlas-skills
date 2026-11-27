"""Name → claimant genes. Counts claimants; never picks among them.

Two backends, same methods:

- **Gene table** (offline): :func:`resolve_names` over SQLite loaded from a
  ``gene_ids.tsv.gz`` (:mod:`gene_identity.table`). Claimants are counted
  over the table's gene universe, which is right for whole-transcriptome
  datasets but gives false "unique" results for a targeted panel.
- **Name Resolver** (network): :func:`resolve_by_taxon` over one species'
  NCBIGene genes. It does not search descendants of a higher taxon.

Methods, in order:

1. ``EXACT_SYMBOL``: the name is a gene's symbol, case-sensitive.
2. ``CASE_INSENSITIVE_SYMBOL``: the same after :func:`normalise_name`. A
   symbol beats other genes' synonyms (``SST`` → Sst even though Lmx1a lists
   ``sst``); those genes stay on the match as ``claimants`` for review.
3. ``UNIQUE_SYNONYM``: exactly one gene lists the name.

Two or more claimants is ``AMBIGUOUS`` and none is ``NO_MATCH``: neither is
guessed. One claimant means only that one gene lists the string, not that the
source means it (``D1`` → Dio1): that judgement is the skill's.
"""

from __future__ import annotations

import csv
import sqlite3
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

from gene_identity import translator
from gene_identity.table import load_gene_tables
from gene_identity.translator import normalise_name

EXACT_SYMBOL = "EXACT_SYMBOL"
CASE_INSENSITIVE_SYMBOL = "CASE_INSENSITIVE_SYMBOL"
UNIQUE_SYNONYM = "UNIQUE_SYNONYM"
AMBIGUOUS = "AMBIGUOUS"
NO_MATCH = "NO_MATCH"
ACCEPTED_METHODS = (EXACT_SYMBOL, CASE_INSENSITIVE_SYMBOL, UNIQUE_SYNONYM)


class GeneIdsUnavailable(RuntimeError):
    """The gene table is missing or empty."""


@dataclass(frozen=True)
class Gene:
    ensembl_id: str
    stats_symbol: str
    stats_col: int
    ncbi_gene_id: str | None
    label: str | None


@dataclass
class GeneMatch:
    """How one name resolved against a gene table.

    ``gene`` is set when ``method`` is one of :data:`ACCEPTED_METHODS`.
    ``claimants`` lists the competing genes for ``AMBIGUOUS``, and for
    ``CASE_INSENSITIVE_SYMBOL`` any other gene that lists the name as a
    synonym.
    """

    name: str
    method: str
    gene: Gene | None = None
    claimants: list[Gene] = field(default_factory=list)

    @property
    def resolved(self) -> bool:
        return self.gene is not None

    def to_dict(self) -> dict:
        def g(x: Gene) -> dict:
            return {
                "ncbi_gene_id": x.ncbi_gene_id, "symbol": x.stats_symbol,
                "label": x.label, "ensembl_id": x.ensembl_id,
            }

        return {
            "name": self.name, "method": self.method,
            "gene": g(self.gene) if self.gene else None,
            "claimants": [g(c) for c in self.claimants],
        }


_GENE_COLS = "ensembl_id, stats_symbol, stats_col, ncbi_gene_id, label"


def _genes(con: sqlite3.Connection, where: str, params: tuple) -> list[Gene]:
    return [
        Gene(*r)
        for r in con.execute(
            f"SELECT {_GENE_COLS} FROM genes WHERE {where} ORDER BY stats_col", params
        )
    ]


def _one_per_ncbi(genes: list[Gene]) -> list[Gene]:
    """Collapse genes sharing an NCBIGene ID (several Ensembl IDs → one gene)
    to the first column, so they count as one claimant."""
    seen: set[str] = set()
    out: list[Gene] = []
    for g in genes:
        key = g.ncbi_gene_id or g.ensembl_id
        if key not in seen:
            seen.add(key)
            out.append(g)
    return out


def _prefer_ncbi(genes: list[Gene]) -> list[Gene]:
    """Of several genes sharing a symbol, keep the one with an NCBIGene ID
    when exactly one has it: the others are extra Ensembl models of the same
    locus (WMB has two ``Kiss1`` columns, one without an NCBIGene record)."""
    with_id = [g for g in genes if g.ncbi_gene_id]
    return with_id if len(genes) > 1 and len(with_id) == 1 else genes


def has_gene_tables(con: sqlite3.Connection) -> bool:
    try:
        return con.execute("SELECT COUNT(*) FROM genes").fetchone()[0] > 0
    except sqlite3.OperationalError:
        return False


def resolve_name(con: sqlite3.Connection, name: str) -> GeneMatch:
    """Resolve one name against the loaded gene table."""
    norm = normalise_name(name)

    exact = _prefer_ncbi(_one_per_ncbi(_genes(con, "stats_symbol = ? OR label = ?", (name, name))))
    if len(exact) == 1:
        return GeneMatch(name, EXACT_SYMBOL, exact[0])
    if len(exact) > 1:
        return GeneMatch(name, AMBIGUOUS, claimants=exact)

    syn_claimants = _one_per_ncbi(_genes(
        con,
        "ncbi_gene_id IN (SELECT ncbi_gene_id FROM gene_synonyms WHERE synonym_norm = ?)",
        (norm,),
    ))
    by_symbol = _prefer_ncbi(_one_per_ncbi(
        _genes(con, "symbol_norm = ? OR label_norm = ?", (norm, norm))
    ))
    if len(by_symbol) == 1:
        others = [g for g in syn_claimants if g.ensembl_id != by_symbol[0].ensembl_id]
        return GeneMatch(name, CASE_INSENSITIVE_SYMBOL, by_symbol[0], claimants=others)
    if len(by_symbol) > 1:
        return GeneMatch(name, AMBIGUOUS, claimants=by_symbol)
    if len(syn_claimants) == 1:
        return GeneMatch(name, UNIQUE_SYNONYM, syn_claimants[0])
    if syn_claimants:
        return GeneMatch(name, AMBIGUOUS, claimants=syn_claimants)
    return GeneMatch(name, NO_MATCH)


def resolve_names(con: sqlite3.Connection, names: Iterable[str]) -> dict[str, GeneMatch]:
    """Resolve names against the loaded gene table. Raises
    :class:`GeneIdsUnavailable` when the table is empty."""
    if not has_gene_tables(con):
        raise GeneIdsUnavailable(
            "The gene table is empty. Build one with `gene-id build-table` or pass "
            "--taxon to use Name Resolver instead."
        )
    return {n: resolve_name(con, n) for n in dict.fromkeys(names) if n}


def resolve_with_table(names: list[str], path: Path) -> list[dict]:
    """Claimant genes for ``names`` from a ``gene_ids.tsv.gz`` (offline)."""
    if not path.is_file():
        raise GeneIdsUnavailable(f"No gene table at {path}.")
    con = sqlite3.connect(":memory:")
    try:
        try:
            load_gene_tables(con, path)
        except (OSError, EOFError, ValueError, csv.Error, sqlite3.Error) as exc:
            # Not a network failure: the file is unreadable (e.g. not a gzip).
            raise GeneIdsUnavailable(f"Cannot read the gene table {path}: {exc}") from exc
        return [m.to_dict() for m in resolve_names(con, names).values()]
    finally:
        con.close()


def resolve_by_taxon(names: list[str], taxon: str) -> list[dict]:
    """Claimant genes for ``names`` among one species' NCBIGene genes, via
    Name Resolver (network).

    Name Resolver ranks by text similarity; a candidate counts as a claimant
    only if the name is one of its exact names (normalised) — the same
    claimant count as the table backend, over the species' full gene set.
    """
    out = []
    for name in dict.fromkeys(n for n in names if n):
        cands = translator.nameres_lookup(name, taxon)
        syns = translator.nameres_synonyms([c["ncbi_gene_id"] for c in cands]) if cands else {}
        norm = normalise_name(name)
        claim = [
            c for c in cands
            if norm in {normalise_name(s) for s in syns.get(c["ncbi_gene_id"], [])}
            or normalise_name(c.get("label") or "") == norm
        ]
        exact = [c for c in claim if c.get("label") == name]
        by_label = [c for c in claim if normalise_name(c.get("label") or "") == norm]
        others: list[dict] = []
        if len(exact) == 1:
            method, gene = EXACT_SYMBOL, exact[0]
        elif len(by_label) == 1:
            # A symbol hit beats other genes' synonyms, as with a gene table:
            # `SST` is Sst although Lmx1a lists it. The rest stay as claimants.
            method, gene = CASE_INSENSITIVE_SYMBOL, by_label[0]
            others = [c for c in claim if c is not by_label[0]]
        elif len(claim) == 1:
            method, gene = UNIQUE_SYNONYM, claim[0]
        else:
            method, gene = (AMBIGUOUS if claim else NO_MATCH), None
        out.append({
            "name": name, "method": method, "taxon": taxon,
            "gene": {"ncbi_gene_id": gene["ncbi_gene_id"], "label": gene["label"]} if gene else None,
            "claimants": [
                {"ncbi_gene_id": c["ncbi_gene_id"], "label": c["label"]} for c in claim
            ] if method == AMBIGUOUS else [
                {"ncbi_gene_id": c["ncbi_gene_id"], "label": c["label"]} for c in others],
            "nameres_candidates": [
                {"ncbi_gene_id": c["ncbi_gene_id"], "label": c["label"]} for c in cands
            ] if method in (AMBIGUOUS, NO_MATCH) else [],
        })
    return out
