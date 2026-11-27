"""``gene-id check``: what a record claims, against the world.

The schema (:mod:`gene_identity.records`) fixes a record's shape. This checks
what no schema can, for every gene a record names (the gene of a ``GENE``
record and each claimant of an ``AMBIGUOUS`` one):

1. **exists**: the NCBIGene ID resolves, as itself, in Translator
   NodeNormalization. A merged or replaced ID is named with its successor.
2. **official symbol**: ``symbol`` is the gene's NodeNorm label, exactly, not
   the source's wording or a synonym.
3. **species** (``GENE``): ``gene_taxon`` is the gene's own taxon, and that
   taxon is the record's ``taxon`` or below it (NCBI Taxonomy lineage), so a
   human gene in a mouse record, or a rat gene under Murinae's wrong branch,
   is caught.
4. **provenance**: the ID was returned by ``gene-id resolve`` in this
   environment. ``resolve`` logs every ID it prints; an ID that never came
   out of the lookup was written from memory, which SKILL.md forbids.

A check that could not run (Translator or NCBI unreachable and nothing
cached) is reported as unchecked, loudly, and is not a problem: a checker
that blocks on a network blip gets switched off.

Caches live in ``$GENE_IDENTITY_CACHE`` (default ``~/.cache/gene-identity``):
``genes.json`` (ID → label, taxon), ``taxa.json`` (taxon → lineage) and
``resolved.json`` (the provenance log). Only successful lookups are cached.
"""

from __future__ import annotations

import json
import os
import tempfile
import urllib.request
import xml.etree.ElementTree as ET
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from gene_identity import records, translator
from gene_identity.translator import NETWORK_ERRORS

EUTILS_URL = os.environ.get(
    "GENE_IDENTITY_EUTILS_URL", "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
)


def cache_dir() -> Path:
    override = os.environ.get("GENE_IDENTITY_CACHE", "").strip()
    return Path(override) if override else Path.home() / ".cache" / "gene-identity"


def _read_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_json(path: Path, data: dict) -> None:
    """Atomic: a reader never sees half a file, and a failed write keeps the old one."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name, suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, sort_keys=True)
        os.replace(tmp, path)
    except OSError:
        pass


# ── Provenance log ───────────────────────────────────────────────────────────


def log_resolved(results: Iterable[dict], *, directory: Path | None = None) -> None:
    """Record every NCBIGene ID a ``resolve`` call printed: its gene, its
    claimants and Name Resolver's candidates."""
    path = (directory or cache_dir()) / "resolved.json"
    log = _read_json(path)
    now = datetime.now(UTC).isoformat(timespec="seconds")
    changed = False
    for r in results:
        genes = [r.get("gene") or {}, *(r.get("claimants") or []),
                 *(r.get("nameres_candidates") or [])]
        for g in genes:
            gid = g.get("ncbi_gene_id") if isinstance(g, dict) else None
            if gid and gid not in log:
                log[gid] = {"name": r.get("name"), "at": now}
                changed = True
    if changed:
        _write_json(path, log)


# ── Lookups ──────────────────────────────────────────────────────────────────


def nodenorm_genes(ids: list[str]) -> dict[str, dict | None]:
    """``{id: {ncbi_gene_id, label, taxon}}`` from NodeNorm; short timeouts,
    because this runs inside a hook."""
    return translator.nodenorm(ids, timeout=20, retries=1)


def ncbi_lineage(taxon: str) -> list[str]:
    """The taxon and every ancestor, as NCBITaxon CURIEs (NCBI E-utilities)."""
    tid = taxon.split(":", 1)[1]
    url = f"{EUTILS_URL}/efetch.fcgi?db=taxonomy&id={tid}&retmode=xml"
    with urllib.request.urlopen(url, timeout=20) as resp:
        root = ET.fromstring(resp.read())
    node = root.find("Taxon")
    if node is None:
        return []
    out = [f"NCBITaxon:{node.findtext('TaxId')}"]
    out += [f"NCBITaxon:{t.findtext('TaxId')}" for t in node.findall("LineageEx/Taxon")]
    return out


@dataclass
class Store:
    """Caches plus the two lookups, injectable so the check runs offline in
    tests and in the catch-rate measurement."""

    directory: Path = field(default_factory=cache_dir)
    lookup_genes: Callable[[list[str]], dict[str, dict | None]] = nodenorm_genes
    lookup_lineage: Callable[[str], list[str]] = ncbi_lineage
    offline: bool = False

    def __post_init__(self) -> None:
        self.genes = _read_json(self.directory / "genes.json")
        self.taxa = _read_json(self.directory / "taxa.json")
        self.resolved = _read_json(self.directory / "resolved.json")
        self._dirty: set[str] = set()

    def get_genes(self, ids: set[str]) -> tuple[dict[str, dict], list[str]]:
        """Records for ``ids`` (``{"missing": True, "replaced_by": ...}`` for
        one NodeNorm doesn't return as itself) and the IDs that couldn't be
        looked up. Misses are not cached, so a passing gap never sticks."""
        want = sorted(ids - self.genes.keys())
        found: dict[str, dict] = {i: self.genes[i] for i in ids if i in self.genes}
        if not want:
            return found, []
        if self.offline:
            return found, want
        try:
            norm = self.lookup_genes(want)
        except NETWORK_ERRORS:
            return found, want
        for i in want:
            n = norm.get(i)
            if n and n.get("ncbi_gene_id") == i:
                self.genes[i] = found[i] = {"label": n.get("label"), "taxon": n.get("taxon")}
                self._dirty.add("genes")
            else:
                found[i] = {"missing": True, "replaced_by": (n or {}).get("ncbi_gene_id")}
        return found, []

    def lineage(self, taxon: str) -> list[str] | None:
        if taxon in self.taxa:
            return self.taxa[taxon]
        if self.offline:
            return None
        try:
            lin = self.lookup_lineage(taxon)
        except (*NETWORK_ERRORS, ET.ParseError):
            return None
        if lin:
            self.taxa[taxon] = lin
            self._dirty.add("taxa")
        return lin or None

    def save(self) -> None:
        for name in self._dirty:
            _write_json(self.directory / f"{name}.json", getattr(self, name))
        self._dirty.clear()


# ── The check ────────────────────────────────────────────────────────────────


def _label(i: int, rec: dict) -> str:
    name = rec.get("name")
    return f"[{i}] ({name})" if isinstance(name, str) else f"[{i}]"


def check(data: Any, store: Store, *, provenance: bool = True) -> tuple[list[str], list[str]]:
    """``(problems, unchecked)``. Schema problems come first and stop the
    check: a record of the wrong shape can't be looked up meaningfully."""
    problems = records.validate(data)
    if problems:
        return problems, []

    # (where, field prefix, gene id, symbol, record) for every gene named.
    named: list[tuple[str, str, str, str, dict]] = []
    for i, rec in enumerate(data):
        where = _label(i, rec)
        if rec["outcome"] == "GENE":
            named.append((where, "", rec["ncbi_gene_id"], rec["symbol"], rec))
        for j, c in enumerate(rec.get("claimants") or []):
            named.append((where, f"claimants[{j}].", c["ncbi_gene_id"], c["symbol"], rec))
    if not named:
        return [], []

    genes, unreachable = store.get_genes({n[2] for n in named})
    unchecked = [f"{gid}: NodeNormalization unreachable and not cached; existence, "
                 "symbol and species unchecked" for gid in unreachable]

    for where, prefix, gid, symbol, rec in named:
        at = f"{where}.{prefix}ncbi_gene_id {gid}"
        if provenance and gid not in store.resolved:
            problems.append(
                f"{at} was never returned by `gene-id resolve` here. Look the gene up "
                "(SKILL.md Step 2) and take its ID and symbol from the output; never "
                "write an ID from memory.")
        g = genes.get(gid)
        if g is None:
            continue
        if g.get("missing"):
            if g.get("replaced_by"):
                problems.append(
                    f"{at} is not a current NCBI gene: NodeNormalization gives "
                    f"{g['replaced_by']} (merged or replaced). Look that gene up and use "
                    "its ID and official symbol.")
            else:
                problems.append(f"{at} does not resolve to an NCBI gene (NodeNormalization).")
            continue
        if symbol != g.get("label"):
            problems.append(
                f"{where}.{prefix}symbol {symbol!r}: {gid} is {g.get('label')!r}. "
                "`symbol` is the gene's official symbol, never the source's wording.")
        if prefix:
            continue
        gene_taxon = g.get("taxon")
        if not gene_taxon:
            unchecked.append(f"{gid}: no taxon in NodeNormalization; species unchecked")
            continue
        if rec["gene_taxon"] != gene_taxon:
            problems.append(
                f"{where}.gene_taxon {rec['gene_taxon']}: {gid} ({g.get('label')}) is a "
                f"{gene_taxon} gene.")
        if gene_taxon != rec["taxon"]:
            lineage = store.lineage(gene_taxon)
            if lineage is None:
                unchecked.append(f"{gid}: NCBI Taxonomy unreachable; whether {gene_taxon} "
                                 f"is within {rec['taxon']} is unchecked")
            elif rec["taxon"] not in lineage:
                problems.append(
                    f"{at} ({g.get('label')}) is a {gene_taxon} gene, outside the record's "
                    f"taxon {rec['taxon']}. Look the name up in that taxon's species.")
    store.save()
    return problems, unchecked
