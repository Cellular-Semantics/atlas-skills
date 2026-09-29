"""Metrics + null comparison for agent picks vs curation.

Pure functions over pick lists and ground truth: no I/O, no network, no agent.
"""
from __future__ import annotations

import math
import random
from collections.abc import Iterable, Mapping


def jaccard(a: Iterable[str], b: Iterable[str]) -> float:
    a_set, b_set = set(a), set(b)
    union = a_set | b_set
    return len(a_set & b_set) / len(union) if union else 1.0


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (centre - half, centre + half)


def bootstrap_ci(
    values: list[float], B: int = 10_000, alpha: float = 0.05, seed: int = 0
) -> tuple[float, float]:
    rng = random.Random(seed)
    means = []
    for _ in range(B):
        sample = [rng.choice(values) for _ in values]
        means.append(sum(sample) / len(sample))
    means.sort()
    return means[int(B * alpha / 2)], means[int(B * (1 - alpha / 2))]


def hypergeom_p_hit(N: int, K: int, k: int) -> float:
    """P[random k-subset of size-N pool intersects K-subset]."""
    if K == 0 or k == 0:
        return 0.0
    from math import comb

    if k > N - K:
        return 1.0
    return 1.0 - comb(N - K, k) / comb(N, k)


def score_picks(
    picks: Mapping[str, list[str]],
    curation: Mapping[str, dict],
    schema: Mapping[str, dict] | None = None,
) -> dict:
    """Compute per-dataset and overall metrics.

    Parameters
    ----------
    picks : dataset_id -> list of picked column names
    curation : dataset_id -> {"columns": [...]} ground truth
    schema : optional dataset_id -> {column_name: ...}; used to compute
             the random-pick null model on the actual obs schema size.
    """
    rows = []
    for dsid, picked in picks.items():
        cur = set(curation.get(dsid, {}).get("columns", []))
        p = set(picked)
        inter = p & cur
        j = jaccard(p, cur)
        hit = 1 if inter or (not p and not cur) else 0
        prec = (len(inter) / len(p)) if p else (1.0 if not cur else 0.0)
        rec = (len(inter) / len(cur)) if cur else (1.0 if not p else 0.0)

        row = {
            "dsid": dsid,
            "n_curated": len(cur),
            "n_picked": len(p),
            "n_intersect": len(inter),
            "jaccard": j,
            "precision": prec,
            "recall": rec,
            "hit": hit,
            "picks": sorted(p),
            "curated": sorted(cur),
            "missed_by_agent": sorted(cur - p),
            "agent_extras": sorted(p - cur),
        }

        # Random-pick null on the obs schema, when we have it.
        if schema and dsid in schema:
            cols = list(schema[dsid].keys())
            N = len(cols)
            K = len(cur)
            k = len(p)
            row["n_obs_cols"] = N
            row["null_hit_p"] = hypergeom_p_hit(N, K, k)

        rows.append(row)

    n = len(rows)
    overall = {"n": n}
    for k in ("jaccard", "precision", "recall"):
        vals = [r[k] for r in rows]
        m = sum(vals) / n if n else 0.0
        sd = (sum((x - m) ** 2 for x in vals) / (n - 1)) ** 0.5 if n > 1 else 0.0
        lo, hi = bootstrap_ci(vals) if n else (0.0, 0.0)
        overall[k] = {"mean": m, "sd": sd, "ci95": [lo, hi]}

    hits = sum(r["hit"] for r in rows)
    wlo, whi = wilson(hits, n)
    overall["hit_rate"] = {"k": hits, "n": n, "p": hits / n if n else 0.0, "ci95": [wlo, whi]}

    null_hit_ps = [r["null_hit_p"] for r in rows if "null_hit_p" in r]
    if null_hit_ps:
        overall["null_hit_rate_expected"] = sum(null_hit_ps) / len(null_hit_ps)

    return {"overall": overall, "per_dataset": rows}
