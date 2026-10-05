"""Live checks against OLS4 and Ubergraph, for the worked examples.

Not part of the unit suite: it hits the network, and both sources change under
us. Run it by hand when touching the query layer.

    python tests/live_examples.py

What it asserts is deliberately loose -- that an expected term is *present* and
roughly where expected, not that a particular term wins. Winning is the agent's
judgement, not the package's.
"""

from __future__ import annotations

import sys

from onto_query.ols import lexical
from onto_query.transport import Transport
from onto_query.ubergraph import Ubergraph

PASS, FAIL = "ok  ", "FAIL"
failures: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    print(f"  [{PASS if condition else FAIL}] {name}{(' -- ' + detail) if detail else ''}")
    if not condition:
        failures.append(name)


def exact_curies(t: Transport, query: str, ontology: str = "uberon") -> list[str]:
    res = lexical(t, query, ontology, probes=("exact",))
    return [h["curie"] for h in res["hits"]]


def skin_zone_seeds(ug: Ubergraph) -> list[str]:
    """The 82 'skin of X' / 'X skin' terms -- deliberately including the
    partition error that makes 'zone of skin' a near miss."""
    rows = ug.cohort("uberon", label_contains="skin", limit=2000)["terms"]
    out = []
    for term in rows:
        for lab in term["labels"]:
            low = lab.lower()
            if low.startswith("skin of ") or (low.endswith(" skin") and low.count(" ") <= 2):
                out.append(term["curie"])
                break
    return sorted(set(out))


def main() -> int:
    t = Transport()
    ug = Ubergraph(t)

    print("lexical exact probe")
    check(
        "skin -> 4 terms incl. zone of skin and skin of body",
        set(exact_curies(t, "skin")) >= {"UBERON:0000014", "UBERON:0002097"},
        str(exact_curies(t, "skin")),
    )
    check(
        "muscle -> muscle organ and muscle structure",
        set(exact_curies(t, "muscle")) == {"UBERON:0001630", "UBERON:0005090"},
    )
    check("full reproductive tract -> nothing", exact_curies(t, "full reproductive tract") == [])
    check(
        "reproductive tract -> reproductive system",
        exact_curies(t, "reproductive tract") == ["UBERON:0000990"],
    )
    check(
        "thoracic spine -> thoracic region of vertebral column",
        exact_curies(t, "thoracic spine") == ["UBERON:0006073"],
    )

    print("lexical probe partitioning")
    res = lexical(t, "skin", "uberon", probes=("exact", "stemmed", "definition"), rows=1000)
    counts = {k: v["num_found"] for k, v in res["probes"].items()}
    check(
        "skin: stemmed is an order of magnitude bigger than exact",
        counts["stemmed"] > 10 * counts["exact"],
        str(counts),
    )
    check("skin: definition-only probe is substantial", counts["definition"] > 50, str(counts))
    check(
        "skin of body is reached by the stemmed probe",
        any(h["curie"] == "UBERON:0002097" and "stemmed" in h["found_by"] for h in res["hits"]),
    )
    by_curie = {h["curie"]: h for h in res["hits"]}
    check(
        "exact probe names the field that matched",
        by_curie["UBERON:0002097"]["found_by"]["exact"]["matched_fields"] == ["related_synonym"],
        str(by_curie["UBERON:0002097"]["found_by"]["exact"]),
    )
    check(
        "stemmed rank is reported and still buries the general term",
        by_curie["UBERON:0002097"]["found_by"]["stemmed"]["rank"] > 20,
        f"skin of body at rank {by_curie['UBERON:0002097']['found_by']['stemmed']['rank']}",
    )
    check(
        "search_config reports uberon takes OLS4 defaults",
        res["search_config"]["uses_ols4_defaults"] is True,
    )
    check(
        "synonym scope is recovered for zone of skin",
        any(
            h["curie"] == "UBERON:0000014" and "skin" in h["synonyms"].get("exact", [])
            for h in res["hits"]
        ),
    )

    print("common ancestors")
    ca = ug.common_ancestors(["UBERON:0000964", "UBERON:0001811"], "uberon")
    full = [s for s in ca["subsumers"] if not s["missing_seeds"] and not s["is_seed"]]
    check(
        "cornea + conjunctiva -> ocular surface region top on IC",
        full[0]["curie"] == "UBERON:0010409",
        f"{full[0]['curie']} {full[0]['labels']}",
    )

    sub_only = ug.common_ancestors(
        ["UBERON:0000964", "UBERON:0001811"], "uberon", predicates=("subClassOf",)
    )
    sub_full = [s for s in sub_only["subsumers"] if not s["missing_seeds"] and not s["is_seed"]]
    check(
        "subClassOf alone loses it",
        "UBERON:0010409" not in {s["curie"] for s in sub_full},
        f"best is {sub_full[0]['labels']}",
    )

    go = ug.common_ancestors(["GO:0006096", "GO:0006099"], "go")
    go_full = [s for s in go["subsumers"] if not s["missing_seeds"] and not s["is_seed"]]
    band = [s for s in go_full if s["ic"] and s["ic"] >= go_full[0]["ic"] - 4]
    check(
        "glycolysis + TCA -> a band of 4, then a cliff",
        len(band) == 4,
        ", ".join(f"{s['labels'][0]} {s['ic']}" for s in band),
    )

    cl = ug.common_ancestors(["CL:0000604", "CL:0000573", "CL:0000636"], "uberon")
    cl_full = [s for s in cl["subsumers"] if not s["missing_seeds"]]
    check(
        "cell types -> retina, cross-ontology",
        cl_full[0]["curie"] == "UBERON:0000966",
        f"{cl_full[0]['curie']} {cl_full[0]['labels']}",
    )

    neg = ug.common_ancestors(["UBERON:0000964", "UBERON:0000981"], "uberon")
    neg_full = [s for s in neg["subsumers"] if not s["missing_seeds"] and not s["is_seed"]]
    check(
        "cornea + femur -> low IC ceiling (no meaningful ancestor)",
        neg_full[0]["ic"] < 40,
        f"ceiling {neg_full[0]['ic']} {neg_full[0]['labels']}",
    )

    print("near-miss detection")
    seeds = skin_zone_seeds(ug)
    skin = ug.common_ancestors(seeds, "uberon")
    zone = next((s for s in skin["subsumers"] if s["curie"] == "UBERON:0000014"), None)
    check(f"skin-zone partition built ({len(seeds)} seeds)", len(seeds) > 50, str(len(seeds)))
    check(
        "zone of skin is a near miss, not full coverage",
        zone is not None and 0 < len(zone["missing_seeds"]) <= 2,
        f"misses {zone['missing_seeds'] if zone else '?'}",
    )
    check(
        "the seed it misses is skin of body",
        zone is not None and zone["missing_seeds"] == ["UBERON:0002097"],
    )

    print("relations and cohort")
    rel = ug.relations("UBERON:0000966", "part_of", "in", target_ontology="cl")
    check("part_of retina -> many CL terms", rel["total"] > 40, str(rel["total"]))
    check("includes retinal cone cell", "CL:0000573" in {x["curie"] for x in rel["terms"]})

    coh = ug.cohort("hsapdv", label_contains="week")
    labels = [lab for x in coh["terms"] for lab in x["labels"]]
    check("hsapdv week cohort found", coh["total"] > 20, str(coh["total"]))
    check(
        "convention is ordinal + 'week post-fertilization stage'",
        any("week post-fertilization stage" in lab for lab in labels),
        labels[0] if labels else "",
    )

    print("guards")
    try:
        ug.common_ancestors(["UBERON:0000964"] * 400, "uberon")
        check("seed cap raises", False)
    except Exception as exc:
        check("seed cap raises rather than hanging", "exceeds" in str(exc))

    print()
    if failures:
        print(f"{len(failures)} failure(s): " + "; ".join(failures))
        return 1
    print("all live checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
