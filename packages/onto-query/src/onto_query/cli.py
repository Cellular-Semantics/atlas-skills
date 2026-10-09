"""``oq`` -- evidence-returning query primitives over OLS4 and Ubergraph.

Every command prints one JSON object with a stable envelope:

    {"tool", "version", "command", "backend", "params", "warnings", "result"}

No command returns a best match, a score, a threshold or a decision. If you
want one of those, that judgement belongs in the calling skill, in the
transcript, where it can be audited.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__, help, releases
from .ols import (
    DEFAULT_ROWS,
    PROBES,
    hierarchy,
    lexical,
    linked_entities,
    neighbours,
    search_config,
)
from .transport import Transport, TransportError
from .ubergraph import (
    DEFAULT_ANCESTOR_PREDICATES,
    MAX_SEEDS,
    PREDICATES,
    SeedLimitExceeded,
    Ubergraph,
)


def _envelope(command: str, backend: str, params: dict, result, warnings: list[str]) -> dict:
    return {
        "tool": "onto-query",
        "version": __version__,
        "command": command,
        "backend": backend,
        "params": params,
        "warnings": warnings,
        "result": result,
    }


def _emit(obj: dict) -> None:
    json.dump(obj, sys.stdout, indent=2, sort_keys=False)
    sys.stdout.write("\n")


class _Fmt(argparse.RawDescriptionHelpFormatter, argparse.ArgumentDefaultsHelpFormatter):
    """Keep hand-wrapped prose intact, and still show defaults."""


def _sub(sub, name, description, epilog, **kw):
    return sub.add_parser(
        name,
        description=description,
        epilog=epilog,
        formatter_class=_Fmt,
        **kw,
    )


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="oq",
        description=help.MAIN,
        epilog=help.MAIN_EPILOG,
        formatter_class=_Fmt,
    )
    p.add_argument("--version", action="version", version=__version__)
    p.add_argument(
        "--timeout",
        type=float,
        default=90.0,
        metavar="SECONDS",
        help="per-request timeout. OLS4 latency is erratic (0.96-28s measured on "
        "identical calls), so be generous. Two retries with backoff on failure.",
    )
    sub = p.add_subparsers(dest="command", required=True, metavar="COMMAND")

    lex = _sub(
        sub,
        "lexical",
        help.LEXICAL,
        help.LEXICAL_EPILOG,
        help="OLS4 lexical probes for one or more strings",
    )
    lex.add_argument(
        "-q",
        "--query",
        action="append",
        required=True,
        metavar="STRING",
        help="string to look for. Repeatable; each is probed independently and "
        "reported separately.",
    )
    lex.add_argument(
        "-o",
        "--ontology",
        required=True,
        metavar="NAME",
        help="ontology short name, e.g. uberon, cl, go, hsapdv. Scoped with "
        "local=true, so imported terms from other ontologies are excluded.",
    )
    lex.add_argument(
        "--probes",
        default="exact,stemmed",
        metavar="LIST",
        help=f"comma-separated, any of: {', '.join(PROBES)}. "
        "'definition' always costs an extra call because it is defined as "
        "the default search minus the stemmed set.",
    )
    lex.add_argument(
        "--rows",
        type=int,
        default=DEFAULT_ROWS,
        metavar="N",
        help="max hits returned per probe. num_found always reports the true "
        "total, so truncation is visible rather than silent; raise this when you "
        "want the lot. For scale: uberon 'muscle' is 768 hits, go 'process' is "
        "4919 (~3.5MB at full width).",
    )

    ca = _sub(
        sub,
        "common-ancestors",
        help.COMMON_ANCESTORS,
        help.COMMON_ANCESTORS_EPILOG,
        help="subsumers of a seed set, with coverage and information content",
    )
    ca.add_argument(
        "-s",
        "--seed",
        action="append",
        required=True,
        metavar="CURIE",
        help="seed term, e.g. UBERON:0000964. Repeatable; capped at "
        f"{MAX_SEEDS} (measured: 82 seeds 0.9s, 718 times out).",
    )
    ca.add_argument(
        "-t",
        "--target-ontology",
        required=True,
        metavar="NAME",
        help="restrict subsumers to this ontology. Independent of where the "
        "seeds come from: CL seeds with -t uberon asks what structure "
        "those cell types share.",
    )
    ca.add_argument(
        "--predicates",
        default=",".join(DEFAULT_ANCESTOR_PREDICATES),
        metavar="LIST",
        help=f"comma-separated, any of: {', '.join(sorted(PREDICATES))}. "
        "Dropping part_of is usually a mistake and will warn.",
    )

    rel = _sub(
        sub,
        "relations",
        help.RELATIONS,
        help.RELATIONS_EPILOG,
        help="terms in a named relation to a term",
    )
    rel.add_argument("curie", metavar="CURIE", help="the anchor term")
    rel.add_argument(
        "-p",
        "--predicate",
        default="part_of",
        metavar="NAME|CURIE",
        help="a shorthand name (" + ", ".join(sorted(PREDICATES)) + ") or any "
        "predicate CURIE, e.g. RO:0002170 for 'connected to'. The shorthands are "
        "aliases, not a limit. `oq term <CURIE> -o <ontology>` lists the "
        "predicates a term actually carries, with their CURIEs, and is the way to "
        "find out what to pass here.",
    )
    rel.add_argument(
        "-d",
        "--direction",
        default="in",
        choices=("in", "out"),
        metavar="IN|OUT",
        help="'in' = what points at the anchor; 'out' = what the anchor points at",
    )
    rel.add_argument(
        "-t",
        "--target-ontology",
        default=None,
        metavar="NAME",
        help="restrict the other end to this ontology. Without it, terms from "
        "every ontology in the store come back.",
    )
    rel.add_argument(
        "--graph",
        default="redundant",
        choices=("redundant", "nonredundant"),
        metavar="REDUNDANT|NONREDUNDANT",
        help="which Ubergraph inference graph to read. 'redundant' is the "
        "transitive closure, so a 'direct' edge is not what you get: "
        "UBERON:0002240 develops_from gives 29 edges there and 1 "
        "(posterior neural tube) in 'nonredundant'.",
    )
    rel.add_argument(
        "--direct",
        action="store_true",
        help="sugar for --graph nonredundant",
    )

    term = _sub(
        sub, "term", help.TERM, help.TERM_EPILOG, help="annotations and relations for one term"
    )
    term.add_argument("curie", metavar="CURIE")
    term.add_argument(
        "-o",
        "--ontology",
        required=True,
        metavar="NAME",
        help="the ontology whose asserted graph the annotations come from",
    )

    coh = _sub(
        sub,
        "cohort",
        help.COHORT,
        help.COHORT_EPILOG,
        help="survey labels to read a naming convention",
    )
    coh.add_argument("-o", "--ontology", required=True, metavar="NAME")
    coh.add_argument(
        "--sibling-of",
        metavar="CURIE",
        help="co-children of this term's direct parents. Cannot be combined "
        "with --under or a text filter.",
    )
    coh.add_argument(
        "--label-contains",
        metavar="SUBSTRING",
        help="terms whose asserted label contains this substring, case-insensitive. "
        "Labels only -- use this to read a naming convention, where a synonym "
        "would be noise.",
    )
    coh.add_argument(
        "--text-contains",
        metavar="SUBSTRING",
        help="terms whose label OR any synonym contains this substring, with the "
        "matched field reported. Use this when looking for a term rather than for "
        "a convention: UBERON:0006073 is labelled 'thoracic region of vertebral "
        "column' and carries 'thoracic spine' only as a synonym, so "
        "--label-contains would miss it.",
    )
    coh.add_argument(
        "--under",
        metavar="CURIE",
        help="restrict to terms inside this region, over subClassOf and part_of. "
        "Composes with either text filter. This is the move for a record whose "
        "own text is ambiguous but whose other fields say where in the body it "
        "came from -- 'cortex' with a kidney in the record.",
    )
    coh.add_argument(
        "--limit",
        type=int,
        default=500,
        metavar="N",
        help="max terms returned; 'truncated' says whether this was hit",
    )

    xr = _sub(
        sub,
        "xrefs",
        help.XREFS,
        help.XREFS_EPILOG,
        help="cross-references for a term, resolved where possible",
    )
    xr.add_argument("curie", metavar="CURIE")
    xr.add_argument(
        "-o",
        "--ontology",
        required=True,
        metavar="NAME",
        help="the ontology the term belongs to",
    )
    xr.add_argument(
        "--no-urls",
        action="store_true",
        help="skip the OLS4 v2 lookup that supplies resolvable URLs and names the "
        "registry each xref came from (saves one request)",
    )

    hi = _sub(
        sub,
        "hierarchy",
        help.HIERARCHY,
        help.HIERARCHY_EPILOG,
        help="ancestors/descendants from OLS4 (works outside Ubergraph)",
    )
    hi.add_argument("curie", metavar="CURIE")
    hi.add_argument("-o", "--ontology", required=True, metavar="NAME")
    hi.add_argument(
        "-d",
        "--direction",
        default="up",
        choices=("up", "down"),
        metavar="UP|DOWN",
        help="'up' for ancestors, 'down' for descendants",
    )
    hi.add_argument(
        "--subsumption-only",
        action="store_true",
        help="follow subClassOf alone and skip the hierarchical comparison "
        "(one request instead of two)",
    )

    nb = _sub(
        sub,
        "neighbours",
        help.NEIGHBOURS,
        help.NEIGHBOURS_EPILOG,
        help="one-hop asserted relations from OLS4 (works outside Ubergraph)",
    )
    nb.add_argument("curie", metavar="CURIE")
    nb.add_argument("-o", "--ontology", required=True, metavar="NAME")
    nb.add_argument(
        "-p",
        "--predicate",
        action="append",
        default=[],
        metavar="NAME|CURIE",
        help="keep only relations on this predicate. Repeatable. Takes a CURIE "
        "such as RO:0002496, or an IRI. Without it the whole one-hop "
        "neighbourhood comes back.",
    )
    nb.add_argument(
        "-t",
        "--target-ontology",
        default=None,
        metavar="NAME",
        help="keep only relations whose other end is in this ontology, matched "
        "on the CURIE prefix.",
    )

    cw = _sub(
        sub,
        "crosswalk",
        help.CROSSWALK,
        help.CROSSWALK_EPILOG,
        help="terms cross-referencing an identifier (reverse of xrefs)",
    )
    cw.add_argument("xref", metavar="CURIE", help="e.g. EHDAA2:0000997")
    cw.add_argument(
        "-t",
        "--target-ontology",
        default=None,
        metavar="NAME",
        help="restrict to terms defined by this ontology",
    )

    rel_v = _sub(
        sub,
        "release",
        help.RELEASE,
        help.RELEASE_EPILOG,
        help="which release each backend serves, and whether they agree",
    )
    rel_v.add_argument("-o", "--ontology", required=True, metavar="NAME")
    rel_v.add_argument(
        "--expect",
        metavar="VERSION",
        help="the release a written reference assumes, e.g. 2025-01-23; sets "
        "matches_expected and warns when the backends have moved on",
    )
    rel_v.add_argument(
        "--cache",
        metavar="PATH",
        help="where to keep the dated cache; defaults to the per-user state "
        "directory, or $ONTO_QUERY_CACHE",
    )
    rel_v.add_argument(
        "--max-age-days",
        type=int,
        default=releases.DEFAULT_MAX_AGE_DAYS,
        metavar="N",
        help="serve from cache while the entry is younger than this; the "
        "default means one check per ontology per day",
    )
    rel_v.add_argument(
        "--refresh",
        action="store_true",
        help="ignore the cache and ask both backends now",
    )

    _sub(
        sub,
        "ontologies",
        help.ONTOLOGIES,
        help.ONTOLOGIES_EPILOG,
        help="ontologies present in Ubergraph",
    )
    return p


def _near_miss_warnings(subsumers: list[dict], n_seeds: int) -> list[str]:
    """Flag a near-miss that outranks every full-coverage candidate on IC.

    That pattern usually means the seed set is wrong rather than the graph. For
    the skin-zone seeds, "zone of skin" has the highest IC of anything returned
    and covers 81 of 82 -- and the seed it misses, "skin of body", should not
    have been in the set.

    Seeds are excluded: the redundant graph is reflexive, so every seed subsumes
    itself and would otherwise be reported as a near miss of itself.
    """
    # Proportional, and only meaningful once there are enough seeds for "most of
    # them" to mean something. With two seeds, missing one is not a near miss.
    tolerance = n_seeds // 10
    if tolerance < 1:
        return []
    full = [s for s in subsumers if not s["missing_seeds"] and s["ic"] is not None]
    best = full[0]["ic"] if full else None
    near = [
        s
        for s in subsumers
        if s["missing_seeds"]
        and not s["is_seed"]
        and s["ic"] is not None
        and len(s["missing_seeds"]) <= tolerance
        and (best is None or s["ic"] > best)
    ]
    if not near:
        return []
    s = near[0]
    return [
        f"{s['curie']} ({'/'.join(s['labels'])}) has a higher IC than any "
        f"full-coverage subsumer but misses {len(s['missing_seeds'])} of {n_seeds} "
        f"seeds ({', '.join(s['missing_seeds'])}); check whether those seeds belong "
        "in the set before discounting it"
    ]


def _run(args: argparse.Namespace) -> dict:
    t = Transport(timeout=args.timeout)

    if args.command == "lexical":
        probes = tuple(s.strip() for s in args.probes.split(",") if s.strip())
        # One config lookup, shared across every query string.
        cfg = search_config(t, args.ontology)
        results = [lexical(t, q, args.ontology, probes, args.rows, config=cfg) for q in args.query]
        warnings = [
            f"{r['query']!r}: probe {name!r} returned {info['returned']} of "
            f"{info['num_found']} hits; raise --rows to see the rest"
            for r in results
            for name, info in r["probes"].items()
            if info["truncated"]
        ]
        if not cfg.get("supports_local", True):
            warnings.append(
                f"{args.ontology} declares no preferred prefix, so OLS4's local=true "
                "filter matches nothing and was omitted; results may include terms "
                "imported from other ontologies. Check each hit's prefix."
            )
        if not cfg.get("uses_ols4_defaults", True):
            warnings.append(
                f"{args.ontology} overrides OLS4's synonym properties "
                f"({', '.join(cfg['synonym_properties'])}), so a 'synonym' match "
                "means something different here -- see result.search_config"
            )
        return _envelope(
            "lexical",
            "ols4",
            {"queries": args.query, "ontology": args.ontology, "probes": list(probes)},
            results,
            warnings,
        )

    if args.command == "release":
        res = releases.check(
            t,
            args.ontology,
            expect=args.expect,
            cache_path=Path(args.cache) if args.cache else None,
            max_age_days=args.max_age_days,
            refresh=args.refresh,
        )
        return _envelope(
            "release",
            "ols4+ubergraph",
            {
                "ontology": args.ontology,
                "expect": args.expect,
                "max_age_days": args.max_age_days,
                "refresh": args.refresh,
            },
            res,
            res.pop("warnings"),
        )

    ug = Ubergraph(t)

    if args.command == "ontologies":
        graphs = ug.named_graphs()
        return _envelope("ontologies", "ubergraph", {}, {"named_graphs": sorted(graphs)}, [])

    if args.command == "common-ancestors":
        preds = tuple(s.strip() for s in args.predicates.split(",") if s.strip())
        warnings = []
        if "part_of" not in preds:
            warnings.append(
                "part_of is not in the predicate set; grouping terms reached only by "
                "part_of will be missing (cornea + conjunctiva yields nothing better "
                "than 'anatomical structure' without it)"
            )
        if not ug.has_ontology(args.target_ontology):
            warnings.append(
                f"{args.target_ontology} is not in Ubergraph; no subsumers can be returned"
            )
        res = ug.common_ancestors(args.seed, args.target_ontology, preds)
        warnings.extend(_near_miss_warnings(res["subsumers"], len(args.seed)))
        return _envelope(
            "common-ancestors",
            "ubergraph",
            {
                "seeds": args.seed,
                "target_ontology": args.target_ontology,
                "predicates": list(preds),
            },
            res,
            warnings,
        )

    if args.command == "relations":
        graph = "nonredundant" if args.direct else args.graph
        res = ug.relations(
            args.curie, args.predicate, args.direction, args.target_ontology, graph
        )
        warnings = []
        if graph == "redundant":
            warnings.append(
                "answered from the redundant graph, which is the transitive "
                "closure: these are not direct edges. Use --direct for the "
                "asserted-and-pruned nonredundant graph."
            )
        return _envelope(
            "relations",
            "ubergraph",
            {
                "curie": args.curie,
                "predicate": args.predicate,
                "direction": args.direction,
                "target_ontology": args.target_ontology,
                "graph": graph,
            },
            res,
            warnings,
        )

    if args.command == "term":
        res = ug.term(args.curie, args.ontology)
        return _envelope(
            "term",
            "ubergraph",
            {"curie": args.curie, "ontology": args.ontology},
            res,
            res.pop("warnings"),
        )

    if args.command == "xrefs":
        res = ug.xrefs(args.curie)
        warnings = []
        if not args.no_urls:
            linked = linked_entities(t, args.ontology, args.curie)
            if err := linked.pop("__error__", None):
                warnings.append(f"URL lookup failed, xrefs are unenriched: {err['message']}")
            for x in res["xrefs"]:
                if extra := linked.get(x["value"]):
                    x["url"] = extra["url"]
                    x["registry"] = extra["registry"]
                    if extra["label"] and extra["label"] not in x["labels"]:
                        x["labels"].append(extra["label"])
        if res["unresolved"]:
            warnings.append(
                f"{len(res['unresolved'])} xref(s) name something Ubergraph does not "
                f"hold, so they carry no label: {', '.join(res['unresolved'][:5])}"
            )
        if not res["mappings"]:
            warnings.append(
                "no SKOS mappings asserted on this term; the xrefs above are "
                "annotations, not logical assertions of equivalence"
            )
        return _envelope(
            "xrefs",
            "ubergraph+ols4",
            {"curie": args.curie, "ontology": args.ontology, "urls": not args.no_urls},
            res,
            warnings,
        )

    if args.command == "hierarchy":
        res = hierarchy(t, args.ontology, args.curie, args.direction, args.subsumption_only)
        warnings = []
        for key in ("subsumption", "hierarchical"):
            if (block := res.get(key)) and block["truncated"]:
                warnings.append(
                    f"{block['relation']}: returned {block['returned']} of "
                    f"{block['total']}; results are incomplete"
                )
        if (h := res.get("hierarchical")) and h["reached_only_via_other_relations"]:
            warnings.append(
                f"{len(h['reached_only_via_other_relations'])} term(s) are reached only "
                "via part_of and similar, not subsumption; a subClassOf-only view would "
                "miss them"
            )
        if args.subsumption_only:
            warnings.append("subsumption only: anything reached via part_of was not looked for")
        return _envelope(
            "hierarchy",
            "ols4",
            {
                "curie": args.curie,
                "ontology": args.ontology,
                "direction": args.direction,
                "subsumption_only": args.subsumption_only,
            },
            res,
            warnings,
        )

    if args.command == "neighbours":
        res = neighbours(
            t,
            args.ontology,
            args.curie,
            tuple(args.predicate),
            args.target_ontology,
        )
        warnings = list(res.pop("warnings"))
        if ext := res["external_targets"]:
            warnings.append(
                f"points outside {args.ontology} at: {', '.join(ext)}. Those targets "
                "may be reasonable over in Ubergraph even when this ontology is not"
            )
        if not res["outgoing"] and not res["incoming"]:
            warnings.append("no asserted relations; check the CURIE and the ontology")
        warnings.append(
            "one hop, asserted only -- no closure, no information content, no common "
            "ancestors. Use `crosswalk` into a resident ontology for those."
        )
        return _envelope(
            "neighbours",
            "ols4",
            {
                "curie": args.curie,
                "ontology": args.ontology,
                "predicates": list(args.predicate) or None,
                "target_ontology": args.target_ontology,
            },
            res,
            warnings,
        )

    if args.command == "crosswalk":
        res = ug.crosswalk(args.xref, args.target_ontology)
        warnings = []
        if res["total"] == 0:
            warnings.append(
                f"no term in Ubergraph cross-references {args.xref}. That means the "
                "bridge was never written down, not that no equivalent exists; try a "
                "lexical search in the target ontology instead"
            )
        elif res["total"] > 1 and not args.target_ontology:
            warnings.append(
                f"{res['total']} terms cite this identifier, across "
                f"{len({d['defined_by'] for d in res['terms']})} ontologies; use -t to "
                "restrict"
            )
        warnings.append(
            "an xref is an annotation, not an assertion of equivalence; treat these "
            "as leads to adjudicate"
        )
        return _envelope(
            "crosswalk",
            "ubergraph",
            {"xref": args.xref, "target_ontology": args.target_ontology},
            res,
            warnings,
        )

    if args.command == "cohort":
        res = ug.cohort(
            args.ontology,
            args.sibling_of,
            args.label_contains,
            args.text_contains,
            args.under,
            args.limit,
        )
        warnings = ["the limit was reached; results are incomplete"] if res["truncated"] else []
        return _envelope(
            "cohort",
            "ubergraph",
            {
                "ontology": args.ontology,
                "sibling_of": args.sibling_of,
                "label_contains": args.label_contains,
                "text_contains": args.text_contains,
                "under": args.under,
                "limit": args.limit,
            },
            res,
            warnings,
        )

    raise AssertionError(f"unhandled command {args.command!r}")


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        _emit(_run(args))
    except (SeedLimitExceeded, ValueError) as exc:
        _emit(
            {
                "tool": "onto-query",
                "version": __version__,
                "command": args.command,
                "error": str(exc),
            }
        )
        return 2
    except TransportError as exc:
        _emit(
            {
                "tool": "onto-query",
                "version": __version__,
                "command": args.command,
                "error": f"transport: {exc}",
            }
        )
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
