"""Clients for Translator NodeNormalization and Name Resolver.

Plain JSON over HTTPS with the standard library. Ported from evidencell
``gene_identity.py`` (Cellular-Semantics/evidencell@7641aab).
"""

from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request
from typing import Any
from urllib.parse import urlencode

# Overridable for tests (e.g. an unreachable URL to exercise a soft skip).
NODENORM_URL = os.environ.get(
    "GENE_IDENTITY_NODENORM_URL", "https://nodenormalization-sri.renci.org"
)
NAMERES_URL = os.environ.get(
    "GENE_IDENTITY_NAMERES_URL", "https://name-resolution-sri.renci.org"
)

# What a failed lookup raises: callers catch these to soft-skip.
NETWORK_ERRORS = (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError)

_NORM_STRIP = re.compile(r"[\s\-_]+")
_TAXON_SUFFIX = re.compile(r" \([A-Z][a-z]{3}\)$")


def normalise_name(name: str) -> str:
    """Comparison form of a gene name: lowercased, spaces/hyphens/underscores
    removed (``5-HT3a`` → ``5ht3a``)."""
    return _NORM_STRIP.sub("", name).lower()


def _http_json(
    url: str, payload: Any | None = None, *, timeout: float = 60, retries: int = 3
) -> Any:
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json", "Accept": "application/json"}
    )
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode())
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
            if attempt == retries - 1:
                raise
            time.sleep(2 ** attempt)
    raise AssertionError("unreachable")


def _ncbi_from_nodenorm(entry: dict | None) -> dict | None:
    """Pick the NCBIGene record out of one NodeNorm result, or None."""
    if not entry:
        return None
    equivalents = entry.get("equivalent_identifiers") or []
    ncbi = next(
        (e for e in equivalents if str(e.get("identifier", "")).startswith("NCBIGene:")), None
    )
    taxa = entry.get("taxa") or (ncbi or {}).get("taxa") or []
    # Without an NCBIGene record the label is Ensembl's, e.g. "Gm2164 (Mmus)".
    label = (ncbi or {}).get("label") or (entry.get("id") or {}).get("label")
    return {
        "ncbi_gene_id": ncbi["identifier"] if ncbi else None,
        "label": _TAXON_SUFFIX.sub("", label) if label else None,
        "taxon": taxa[0] if taxa else None,
        "equivalent_ids": [
            e["identifier"] for e in equivalents
            if str(e.get("identifier", "")).split(":")[0] in ("MGI", "HGNC", "RGD")
        ],
    }


def nodenorm(
    curies: list[str], *, batch: int = 1000, timeout: float = 60, retries: int = 3
) -> dict[str, dict | None]:
    """Normalise CURIEs with NodeNormalization (``conflate: false``).

    Returns ``{curie: {ncbi_gene_id, label, taxon, equivalent_ids} | None}``.
    """
    out: dict[str, dict | None] = {}
    for i in range(0, len(curies), batch):
        chunk = curies[i:i + batch]
        res = _http_json(
            f"{NODENORM_URL}/get_normalized_nodes", {"curies": chunk, "conflate": False},
            timeout=timeout, retries=retries,
        )
        for c in chunk:
            out[c] = _ncbi_from_nodenorm(res.get(c))
    return out


def nameres_synonyms(
    ncbi_ids: list[str], *, batch: int = 250, timeout: float = 120, retries: int = 3
) -> dict[str, list[str]]:
    """Every name Name Resolver holds for each NCBIGene ID (``/synonyms``)."""
    out: dict[str, list[str]] = {}
    for i in range(0, len(ncbi_ids), batch):
        chunk = ncbi_ids[i:i + batch]
        res = _http_json(
            f"{NAMERES_URL}/synonyms", {"preferred_curies": chunk},
            timeout=timeout, retries=retries,
        )
        for c in chunk:
            rec = res.get(c) or {}
            out[c] = list(dict.fromkeys(rec.get("names") or []))
    return out


def nameres_lookup(name: str, taxon: str, *, limit: int = 10) -> list[dict]:
    """Name Resolver candidates for ``name`` among NCBIGene genes of ``taxon``.

    Always restricted to ``only_prefixes=NCBIGene``: with ``only_taxa`` alone,
    records without taxon metadata (MGI, FlyBase, ZFIN) slip through.
    """
    q = urlencode({
        "string": name, "biolink_type": "Gene", "only_taxa": taxon,
        "only_prefixes": "NCBIGene", "limit": limit, "autocomplete": "false",
    })
    res = _http_json(f"{NAMERES_URL}/lookup?{q}")
    return [
        {"ncbi_gene_id": r["curie"], "label": r.get("label"), "taxa": r.get("taxa") or []}
        for r in res or []
    ]


def translator_versions() -> dict[str, str | None]:
    """Babel / service versions for provenance headers."""
    out: dict[str, str | None] = {}
    for key, url in (("nodenorm", NODENORM_URL), ("nameres", NAMERES_URL)):
        try:
            st = _http_json(f"{url}/status", timeout=20, retries=2)
        except NETWORK_ERRORS:
            st = {}
        out[f"{key}_babel_version"] = st.get("babel_version")
        out[f"{key}_version"] = st.get("version") if key == "nodenorm" else st.get("nameres_version")
    return out
