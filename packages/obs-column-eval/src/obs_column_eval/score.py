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

    return {"overall": summarise(rows), "per_dataset": rows}


def summarise(rows: list[Mapping]) -> dict:
    """The ``overall`` block for a list of per-dataset rows: mean, sd and a
    bootstrap 95% CI for each metric, and the hit rate with a Wilson CI."""
    n = len(rows)
    overall: dict = {"n": n}
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
    return overall


def _unique_datasets(rows: list[Mapping], manifest: Mapping[str, dict]) -> list[dict]:
    """Collapse rows that are versions of one CELLxGENE dataset into one row.

    Versions are linked when they share a CxG dataset id. A merged row averages
    jaccard, precision and recall across its versions, and counts as a hit only
    if every version was a hit -- so a dataset scored twice weighs once.
    """
    groups: list[tuple[set[str], list[Mapping]]] = []
    for row in rows:
        ids = set(manifest[row["dsid"]].get("cxg_dataset_ids") or [row["dsid"]])
        linked = [g for g in groups if g[0] & ids]
        merged_ids = ids.union(*(g[0] for g in linked))
        merged_rows = [row] + [r for g in linked for r in g[1]]
        groups = [g for g in groups if g not in linked] + [(merged_ids, merged_rows)]
    out = []
    for _, members in groups:
        out.append({
            "dsid": sorted(r["dsid"] for r in members)[0],
            "versions": sorted(r["dsid"] for r in members),
            **{k: sum(r[k] for r in members) / len(members)
               for k in ("jaccard", "precision", "recall")},
            "hit": min(r["hit"] for r in members),
        })
    return out


def score_by_tier(rows: list[Mapping], manifest: Mapping[str, dict]) -> dict:
    """Split per-dataset rows by the test-set tier each dataset belongs to.

    Returns ``{"tiers": {tier: overall}, "all": overall, "by_group": {tier:
    {sheet: {"n", "jaccard"}}}, "outside_test_set": [dsid]}``.

    Each tier is scored exactly as its datasets are listed, so ``n73`` still
    reproduces its published figure, duplicates and all. ``all`` counts each
    CELLxGENE dataset once (see ``_unique_datasets``): the four n73 holds under
    two versions would otherwise weigh double in a combined figure.
    """
    inside = [r for r in rows if r["dsid"] in manifest]
    tiers: dict[str, list[Mapping]] = {}
    by_group: dict[str, dict[str, list[float]]] = {}
    for row in inside:
        entry = manifest[row["dsid"]]
        tiers.setdefault(entry["tier"], []).append(row)
        by_group.setdefault(entry["tier"], {}).setdefault(entry["group"], []).append(row["jaccard"])
    unique = _unique_datasets(inside, manifest)
    return {
        "tiers": {t: summarise(rs) for t, rs in sorted(tiers.items())},
        "all": {**summarise(unique), "n_entries": len(inside)},
        "by_group": {t: {g: {"n": len(js), "jaccard": sum(js) / len(js)}
                         for g, js in sorted(groups.items())}
                     for t, groups in sorted(by_group.items())},
        "outside_test_set": sorted(r["dsid"] for r in rows if r["dsid"] not in manifest),
    }


def score_by_field_type(
    picks: Mapping[str, object],
    gold: Mapping[str, dict],
    field_types: Iterable[str],
    schema: Mapping[str, dict] | None = None,
) -> dict:
    """Score a picks file one field type at a time.

    Only datasets the gold set was *curated for* on a given field type are
    scored on it. Scoring the rest would count every correct tissue pick on a
    cell-type-only dataset as a false positive, which would say more about the
    gold set's coverage than about the agent.
    """
    from .gold import flatten

    out = {}
    for ft in field_types:
        eligible = {dsid for dsid, entry in gold.items()
                    if ft in entry.get("curated_for", [])}
        ft_picks = {d: p for d, p in flatten(picks, ft).items() if d in eligible}
        ft_gold = {d: {"columns": gold[d]["columns"].get(ft, [])} for d in eligible}
        if not ft_picks:
            out[ft] = {"overall": {"n": 0}, "per_dataset": [],
                       "skipped": "no picks for any dataset curated for this "
                                  "field type"}
            continue
        result = score_picks(ft_picks, ft_gold, schema)
        result["n_eligible_datasets"] = len(eligible)
        result["n_scored"] = len(ft_picks)
        out[ft] = result
    return out
