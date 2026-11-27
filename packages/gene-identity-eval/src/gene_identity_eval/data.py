"""The committed NLM-Gene snapshot: cases, tiers and provenance."""

from __future__ import annotations

import json
from importlib import resources

PACKAGE = "gene_identity_eval"


def _read(name: str) -> str:
    return resources.files(PACKAGE).joinpath(f"data/nlm_gene/{name}").read_text(encoding="utf-8")


def source() -> dict:
    return json.loads(_read("SOURCE.json"))


def cases() -> dict[str, dict]:
    """Every case built from the test split, keyed by id."""
    out = {}
    for line in _read("cases.jsonl").splitlines():
        if line.strip():
            c = json.loads(line)
            out[c["id"]] = c
    return out


def tiers() -> dict[str, dict]:
    """``{tier: {seed, caps, ids}}``."""
    return json.loads(_read("tiers.json"))


def tier_cases(tier: str) -> dict[str, dict]:
    all_cases = cases()
    return {i: all_cases[i] for i in tiers()[tier]["ids"]}
