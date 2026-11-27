"""Scoring gene-id-curation records against NLM-Gene cases. Pure functions.

A case passes when the record's ``outcome`` matches; for ``GENE`` its
``ncbi_gene_id`` must be one of ``accept``; where the expected ``kind`` is
set it must match (NLM-Gene's never is: it doesn't say family vs complex).
``method`` and ``rationale`` are not scored. These are the gic rules, so
numbers on both sets mean the same thing. One addition: a ``generic``
mention, one that is none of the gold gene's listed names, also passes as
``NO_SINGLE_GENE``. That flag holds the classes the gold resolved to one
member ("Kinases" → AKT1, "GPCR" → Gpr34), where SKILL.md asks for
``NO_SINGLE_GENE``; it also holds specific names Translator doesn't list
("CCL-2"), where the allowance rarely matters because the skill doesn't call
those families. ``summarise`` reports the flagged cases separately and counts
the passes that needed the allowance, so the leniency is visible.

**Strata** come from the lookup's own answer (``resolver_baseline``), which is
the whole point of the skill: where the lookup is already right, the skill
must not get in the way; where it is wrong, ambiguous or empty, the skill has
to do the work.
"""

from __future__ import annotations

import random
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping

STRATA = ("easy", "lookup_wrong", "lookup_ambiguous", "lookup_no_match", "family")


def score(record: Mapping | None, expected: Mapping) -> tuple[bool, str]:
    if not isinstance(record, Mapping):
        return False, "no record"
    got, want = record.get("outcome"), expected["outcome"]
    if want == "GENE" and expected.get("generic") and got == "NO_SINGLE_GENE":
        return True, "no single gene, for a generic mention"
    if got != want:
        return False, f"outcome {got} (want {want})"
    if want == "GENE":
        accepted = {a["ncbi_gene_id"] for a in expected["accept"]}
        gid = record.get("ncbi_gene_id")
        if gid not in accepted:
            return False, (f"gene {gid or '?'} {record.get('symbol') or ''}".rstrip()
                           + f" (want {' or '.join(sorted(accepted))})")
        return True, f"gene {gid}"
    if expected.get("kind") and record.get("kind") != expected["kind"]:
        return False, f"kind {record.get('kind')} (want {expected['kind']})"
    return True, want


def baseline_record(baseline: Mapping | None) -> dict:
    """The lookup's answer as a record: its gene when it named one."""
    if not baseline or baseline.get("error"):
        return {"outcome": "UNRESOLVED", "kind": "LOOKUP_FAILED"}
    gene = baseline.get("gene")
    if gene:
        return {"outcome": "GENE", "ncbi_gene_id": gene["ncbi_gene_id"], "symbol": gene.get("label")}
    return {"outcome": "UNRESOLVED", "kind": baseline.get("method")}


def stratum(case: Mapping) -> str:
    exp, base = case["expected"], case.get("resolver_baseline") or {}
    if exp["outcome"] == "NO_SINGLE_GENE":
        return "family"
    if score(baseline_record(base), exp)[0]:
        return "easy"
    method = base.get("method")
    if method == "AMBIGUOUS":
        return "lookup_ambiguous"
    if method == "NO_MATCH" or base.get("error"):
        return "lookup_no_match"
    return "lookup_wrong"


def select_tier(cases: Iterable[Mapping], caps: Mapping[str, int], seed: int) -> list[str]:
    """Case ids for a tier: up to ``caps[stratum]`` per stratum, drawn with a
    fixed seed, in a stable order. Selection never looks at an agent's answer."""
    by: dict[str, list[str]] = defaultdict(list)
    for c in cases:
        by[stratum(c)].append(c["id"])
    rng = random.Random(seed)
    out: list[str] = []
    for s in STRATA:
        ids = sorted(by.get(s, []))
        take = min(caps.get(s, 0), len(ids))
        out += sorted(rng.sample(ids, take))
    return out


def summarise(rows: Iterable[Mapping], cases: Mapping[str, Mapping]) -> dict:
    """Metrics over scored rows (``{id, passed, record}``); unscored rows
    (voided, errors) are left out and counted.

    - ``accuracy``: share of cases passed, overall and per stratum;
    - ``gene_id_accuracy``: on cases expecting one gene;
    - ``family_recall``: share of family mentions reported as no single gene;
    - ``baseline_accuracy`` on the same scored cases, and the ``lift``;
    - ``refuse_all_accuracy``: a policy that answers NO_SINGLE_GENE to everything,
      scored the same way. Accepting that outcome for ``generic`` mentions and
      families means this is well above zero; read ``accuracy`` against it, and
      read ``by_name_match["names_gene"]`` (the strict cases) beside it.
    """
    rows = list(rows)
    scored = [r for r in rows if r.get("passed") is not None]
    per: dict[str, Counter] = defaultdict(Counter)
    gene, fam = Counter(), Counter()
    by_name: dict[str, Counter] = defaultdict(Counter)
    allowance = 0
    base_pass = 0
    refuse_pass = 0
    refuse = {"outcome": "NO_SINGLE_GENE"}
    for r in scored:
        case = cases[r["id"]]
        s = stratum(case)
        per[s]["n"] += 1
        per[s]["passed"] += bool(r["passed"])
        b = score(baseline_record(case.get("resolver_baseline")), case["expected"])[0]
        per[s]["baseline_passed"] += b
        base_pass += b
        refuse_pass += score(refuse, case["expected"])[0]
        if case["expected"]["outcome"] == "GENE":
            gene["n"] += 1
            gene["passed"] += bool(r["passed"])
            flag = "generic" if case["expected"].get("generic") else "names_gene"
            by_name[flag]["n"] += 1
            by_name[flag]["passed"] += bool(r["passed"])
            by_name[flag]["baseline_passed"] += b
            if r["passed"] and (r.get("record") or {}).get("outcome") == "NO_SINGLE_GENE":
                allowance += 1
        else:
            fam["n"] += 1
            fam["recalled"] += (r.get("record") or {}).get("outcome") == "NO_SINGLE_GENE"
    n = len(scored)
    passed = sum(1 for r in scored if r["passed"])

    def rate(a: int, b: int) -> float | None:
        return round(a / b, 4) if b else None

    acc, base = rate(passed, n), rate(base_pass, n)
    return {
        "n_cases": len(rows),
        "n_scored": n,
        "passed": passed,
        "accuracy": acc,
        "baseline_accuracy": base,
        "refuse_all_accuracy": rate(refuse_pass, n),
        "lift": round(acc - base, 4) if acc is not None and base is not None else None,
        "gene_id_accuracy": rate(gene["passed"], gene["n"]),
        "family_recall": rate(fam["recalled"], fam["n"]),
        "by_name_match": {k: {"n": v["n"], "passed": v["passed"],
                              "accuracy": rate(v["passed"], v["n"]),
                              "baseline_accuracy": rate(v["baseline_passed"], v["n"])}
                          for k, v in sorted(by_name.items())},
        "passed_by_generic_allowance": allowance,
        "per_stratum": {s: {"n": per[s]["n"], "passed": per[s]["passed"],
                            "accuracy": rate(per[s]["passed"], per[s]["n"]),
                            "baseline_accuracy": rate(per[s]["baseline_passed"], per[s]["n"])}
                        for s in STRATA if per[s]["n"]},
        "voided": sorted(r["id"] for r in rows if r.get("voided")),
        "errors": sorted(r["id"] for r in rows if r.get("error")),
    }
