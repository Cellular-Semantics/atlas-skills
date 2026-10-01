"""The command line. Every subcommand prints JSON on stdout.

Exit codes are meaningful, because the whole design rests on a failure being
able to stop something: 0 success, 1 an error, 2 "what you asked me to check
does not check out". ``validate`` returns 2 on any failed gate, so it can sit in
a pipeline and block rather than warn.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from . import __version__, dossier, ehdaa2, evaluate, extract, fold, pipeline, validate
from .cache import Cache
from .config import Config
from .errors import OntomapError
from .index import LexicalIndex
from .index import build as build_index
from .ols import Ols
from .ubergraph import Ubergraph

ONTOLOGY_FOR_FIELD = {"tissue": "UBERON", "disease": "MONDO"}


def _emit(payload: Any) -> None:
    json.dump(payload, sys.stdout, indent=2, sort_keys=False, default=str)
    sys.stdout.write("\n")


def _services(args: argparse.Namespace) -> tuple[Ubergraph, Ols]:
    cache = Cache(args.cache, enabled=not args.no_cache)
    return Ubergraph(cache=cache), Ols(cache=cache)


def _indexes(ubergraph: Ubergraph, config: Config) -> dict[str, LexicalIndex]:
    wanted = {
        ONTOLOGY_FOR_FIELD[name] for name in config.fields if name in ONTOLOGY_FOR_FIELD
    }
    return {prefix: build_index(ubergraph, prefix=prefix) for prefix in sorted(wanted)}


def _read_json(path: str) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def cmd_extract(args: argparse.Namespace) -> int:
    config = Config.load(args.config)
    records = extract.extract(extract.read_table(args.table), config)
    in_scope = sum(1 for r in records if r["scope"] == "in_scope")
    payload = {
        "records": records,
        "summary": {
            "rows": len(records),
            "in_scope": in_scope,
            "out_of_scope": len(records) - in_scope,
            "distinct_values": {
                name: len(extract.distinct_values(records, name)) for name in config.fields
            },
        },
    }
    if args.out:
        Path(args.out).write_text(json.dumps(payload, indent=1), encoding="utf-8")
        _emit(payload["summary"])
    else:
        _emit(payload)
    return 0


def cmd_map(args: argparse.Namespace) -> int:
    config = Config.load(args.config)
    ubergraph, ols = _services(args)
    records = _read_json(args.records)["records"]
    indexes = _indexes(ubergraph, config)
    mapped = [pipeline.map_record(r, config, ubergraph=ubergraph, indexes=indexes, ols=ols)
              for r in records]
    payload = {"records": mapped, "summary": _summarise(mapped, config)}
    if args.out:
        Path(args.out).write_text(json.dumps(payload, indent=1, default=str), encoding="utf-8")
        _emit(payload["summary"])
    else:
        _emit(payload)
    return 0


def _summarise(records: list[dict[str, Any]], config: Config) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for name in config.fields:
        assigned = refused = 0
        rules: dict[str, int] = {}
        for record in records:
            result = (record.get("mapped") or {}).get(name)
            if result is None:
                continue
            rules[result.get("rule", "?")] = rules.get(result.get("rule", "?"), 0) + 1
            if result.get("term_id"):
                assigned += 1
            else:
                refused += 1
        summary[name] = {
            "assigned": assigned,
            # Not a shortfall. A refusal is the designed output when nothing
            # defensible matched, and this count going up after a fix is good.
            "refused_or_unresolved": refused,
            "by_rule": dict(sorted(rules.items(), key=lambda kv: -kv[1])),
        }
    return summary


def cmd_dossier(args: argparse.Namespace) -> int:
    config = Config.load(args.config)
    ubergraph, ols = _services(args)
    records = _read_json(args.records)["records"]
    indexes = _indexes(ubergraph, config)

    counts: dict[tuple[str, str], int] = {}
    unresolved: dict[tuple[str, str], dict[str, Any]] = {}
    for record in records:
        if record.get("scope") != "in_scope":
            continue
        for name, result in (record.get("mapped") or {}).items():
            if args.field and name != args.field:
                continue
            if result.get("term_id") and not result.get("needs_review"):
                continue
            key = (name, result.get("raw", ""))
            counts[key] = counts.get(key, 0) + 1
            unresolved.setdefault(key, result)

    ordered = sorted(unresolved, key=lambda k: -counts[k])[: args.limit]
    dossiers = [
        dossier.build(
            name, value, unresolved[(name, value)],
            count=counts[(name, value)],
            ubergraph=ubergraph,
            index=indexes.get(ONTOLOGY_FOR_FIELD.get(name, "")),
            ols=ols if not args.no_search else None,
            ontology=ONTOLOGY_FOR_FIELD.get(name, "UBERON"),
        )
        for name, value in ordered
    ]
    payload = {
        "dossiers": dossiers,
        "summary": {
            "unresolved_distinct_values": len(unresolved),
            "written": len(dossiers),
            "samples_covered": sum(counts[k] for k in ordered),
            "samples_remaining": sum(counts[k] for k in unresolved if k not in set(ordered)),
        },
    }
    if args.out:
        Path(args.out).write_text(json.dumps(payload, indent=1, default=str), encoding="utf-8")
        _emit(payload["summary"])
    else:
        _emit(payload)
    return 0


def cmd_fold(args: argparse.Namespace) -> int:
    records = _read_json(args.records)["records"]
    judgements = fold.load_judgements(_read_json(args.judgements) if args.judgements else [])
    folded = fold.fold(records, judgements)
    payload = {
        "records": folded,
        "worktable": fold.worktable(folded),
        "summary": {
            "rows": len(folded),
            "by_status": _counts(r.get("row_status") for r in folded),
            "judgement_rows": sum(
                1
                for r in folded
                for v in (r.get("mapped") or {}).values()
                if v.get("curator") not in (None, "rules")
            ),
        },
    }
    if args.out:
        Path(args.out).write_text(json.dumps(payload, indent=1, default=str), encoding="utf-8")
        _emit(payload["summary"])
    else:
        _emit(payload)
    return 0


def _counts(values: Any) -> dict[str, int]:
    out: dict[str, int] = {}
    for value in values:
        out[str(value)] = out.get(str(value), 0) + 1
    return dict(sorted(out.items()))


def cmd_validate(args: argparse.Namespace) -> int:
    ubergraph, ols = _services(args)
    records = _read_json(args.records)["records"]

    terms: list[dict[str, Any]] = []
    claims: list[dict[str, Any]] = []
    for record in records:
        for name, result in (record.get("mapped") or {}).items():
            if result.get("term_id"):
                terms.append({"id": result["term_id"], "name": result.get("term_name"),
                              "field": name})
            # Rejected alternatives are ids too, and someone will read them as
            # evidence. They get the same gates.
            for candidate in result.get("candidates") or []:
                if candidate.get("id") and candidate.get("label"):
                    terms.append({"id": candidate["id"], "name": candidate["label"],
                                  "field": name})
            if result.get("exemplar_specific_term_id"):
                claims.append(result)

    seen: set[tuple[str, str | None]] = set()
    unique = []
    for term in terms:
        key = (term["id"], term.get("name"))
        if key not in seen:
            seen.add(key)
            unique.append(term)

    results = []
    for field_name in sorted({t["field"] for t in unique}):
        results += validate.check_terms(
            [t for t in unique if t["field"] == field_name], ols, field=field_name
        )
    results += validate.check_broad_matches(claims, ubergraph)

    summary = validate.summarise(results)
    summary["ehdaa2_data_version"] = ehdaa2.data_version()
    _emit(summary)
    return 2 if summary["failed"] else 0


def cmd_evaluate(args: argparse.Namespace) -> int:
    records = _read_json(args.records)["records"]
    gold_raw = _read_json(args.gold)
    gold = {int(k): v for k, v in gold_raw.get("rows", {}).items()}
    report = {
        "gold_complete": gold_raw.get("complete", False),
        "fields": [
            {
                **evaluate.compare(records, gold, field=name,
                                   gold_complete=gold_raw.get("complete", False)),
                **evaluate.coverage(records, field=name),
            }
            for name in (args.field or ["tissue", "stage", "sex", "disease", "species"])
        ],
    }
    _emit(report)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ontomap", description=__doc__)
    parser.add_argument("--version", action="version", version=f"ontomap {__version__}")
    parser.add_argument("--cache", default=None, help="cache directory")
    parser.add_argument("--no-cache", action="store_true", help="do not read or write the cache")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("extract", help="pull declared columns, fold units, flag scope")
    p.add_argument("table")
    p.add_argument("--config", required=True)
    p.add_argument("--out")
    p.set_defaults(func=cmd_extract)

    p = sub.add_parser("map", help="run the rule ladders in dependency order")
    p.add_argument("records")
    p.add_argument("--config", required=True)
    p.add_argument("--out")
    p.set_defaults(func=cmd_map)

    p = sub.add_parser("dossier", help="assemble the judgement interface for unresolved values")
    p.add_argument("records")
    p.add_argument("--config", required=True)
    p.add_argument("--field")
    p.add_argument("--limit", type=int, default=50)
    p.add_argument("--no-search", action="store_true", help="omit OLS lexical candidates")
    p.add_argument("--out")
    p.set_defaults(func=cmd_dossier)

    p = sub.add_parser("fold", help="combine rules and judgement; judgement wins")
    p.add_argument("records")
    p.add_argument("--judgements")
    p.add_argument("--out")
    p.set_defaults(func=cmd_fold)

    p = sub.add_parser("validate", help="run the gates; exit 2 on any failure")
    p.add_argument("records")
    p.set_defaults(func=cmd_validate)

    p = sub.add_parser("evaluate", help="score against a gold set, per rule path")
    p.add_argument("records")
    p.add_argument("--gold", required=True)
    p.add_argument("--field", action="append")
    p.set_defaults(func=cmd_evaluate)

    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except OntomapError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
