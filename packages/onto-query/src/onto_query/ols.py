"""Lexical probes against OLS4.

Three probes, run independently and merged without being collapsed into a
verdict:

  exact       queryFields=label,synonym with exact=true -> whole-string match
  stemmed     queryFields=label,synonym                 -> tokenised, stemmed
  definition  the default search, minus the stemmed set

What the two parameters do, since neither is obvious:

- ``exact=true`` alone is close to meaningless. Without ``queryFields`` it still
  searches definitions and degenerates to token matching: ``q=skin&exact=true``
  returns 281 of 282 hits. Paired with ``queryFields=label,synonym`` it means
  whole-string.
- ``local=true`` scopes to one ontology. Without it, ``ontology=uberon`` also
  returns imported GO, CL, PR, NBO and BSPO terms -- 347 hits for "skin" rather
  than 282. ``isDefiningOntology`` is null on every document, so it cannot be
  used instead.

What ``synonym`` covers is per-ontology, not fixed: OLS4 exposes
``synonymProperties`` in each ontology's config, and it differs (EFO declares
``efo:alternative_term`` alongside ``hasExactSynonym``; most OBO ontologies
leave it empty and take OLS4's defaults). That config is reported alongside the
hits so the scope of a search is visible rather than assumed.

On ordering: OLS4 returns no relevance score -- not in the default document, and
not via ``fl=score`` or ``fieldList=score``. The rank of a hit within a probe is
therefore the only trace of Solr's scoring, and it is reported for what it is
worth. It segregates match channels reliably (definition-only hits rank strictly
below every lexical hit: 111-282 of 282 for "skin", 665-1291 of 1291 for
"muscle") and is unreliable within the lexical band (``skin of body`` ranks 46th,
``muscle organ`` 360th). Useful as a loose signal, not as a basis for choosing.
"""

from __future__ import annotations

from dataclasses import dataclass

from .transport import Transport

# Scoped synonym fields, as OLS4 names them. `synonym` is the union of these.
SYNONYM_FIELDS = {
    "exact": "exact_synonyms",
    "broad": "broad_synonyms",
    "narrow": "narrow_synonyms",
    "related": "related_synonyms",
}

FIELD_LIST = ",".join(
    ["obo_id", "iri", "label", "description", "synonym", *SYNONYM_FIELDS.values()]
)

LEXICAL_QUERY_FIELDS = "label,synonym"

# Enough for a broad single word in a mid-sized ontology (uberon "muscle" is 768)
# without dragging back megabytes for the pathological ones (go "process" is
# 4919 hits, 3.5MB). num_found always reports the true total, so truncation is
# visible rather than silent; raise --rows when you actually want everything.
DEFAULT_ROWS = 200

PROBES = ("exact", "stemmed", "definition")


@dataclass(frozen=True)
class Hit:
    curie: str
    label: str
    definition: str | None
    synonyms: dict[str, list[str]]
    found_by: dict[str, dict]

    def as_dict(self) -> dict:
        return {
            "curie": self.curie,
            "label": self.label,
            "definition": self.definition,
            "synonyms": self.synonyms,
            "found_by": self.found_by,
        }


def _params(query: str, ontology: str, probe: str, rows: int, local: bool = True) -> dict[str, str]:
    p = {
        "q": query,
        "ontology": ontology,
        "obsoletes": "false",
        "rows": str(rows),
        "fieldList": FIELD_LIST,
    }
    if local:
        p["local"] = "true"
    if probe in ("exact", "stemmed"):
        p["queryFields"] = LEXICAL_QUERY_FIELDS
    if probe == "exact":
        p["exact"] = "true"
    return p


def _synonyms(doc: dict) -> dict[str, list[str]]:
    """Scoped synonym lists, straight from OLS4's scoped fields."""
    out = {scope: list(doc.get(field) or []) for scope, field in SYNONYM_FIELDS.items()}
    return {k: v for k, v in out.items() if v}


def _matched_fields(doc: dict, query: str) -> list[str]:
    """Which fields the query matched, for the exact probe only.

    Exact means whole-string, so this is a reliable comparison rather than a
    guess. It is deliberately not attempted for the stemmed probe: stemming and
    tokenisation make a client-side reconstruction wrong more often than right
    ("muscles" matches "muscle organ" at the backend but matches no field here),
    and OLS4 offers no highlighting to ask instead.
    """
    q = query.casefold().strip()
    matched = []
    if (doc.get("label") or "").casefold().strip() == q:
        matched.append("label")
    for scope, field in SYNONYM_FIELDS.items():
        if any(s.casefold().strip() == q for s in (doc.get(field) or [])):
            matched.append(f"{scope}_synonym")
    return matched


def _search(
    t: Transport, query: str, ontology: str, probe: str, rows: int, local: bool = True
) -> dict:
    resp = t.ols4_search(_params(query, ontology, probe, rows, local))
    body = resp.get("response", {})
    return {"docs": body.get("docs", []), "num_found": body.get("numFound", 0)}


def _to_hit(doc: dict, found_by: dict[str, dict]) -> Hit | None:
    curie = doc.get("obo_id")
    if not curie:
        return None
    desc = doc.get("description")
    return Hit(
        curie=curie,
        label=doc.get("label") or "",
        definition=desc[0] if isinstance(desc, list) and desc else (desc or None),
        synonyms=_synonyms(doc),
        found_by=found_by,
    )


def search_config(t: Transport, ontology: str) -> dict:
    """What OLS4 treats as label, synonym and definition for this ontology.

    An empty list means the ontology declares nothing and OLS4's defaults apply
    (the oboInOwl synonym properties). A populated list is the ontology
    overriding them, which changes what a `synonym` match means.
    """
    try:
        cfg = t.ols4_ontology(ontology).get("config", {}) or {}
    except Exception as exc:  # config is nice to have, not worth failing over
        return {"unavailable": str(exc)}
    # local=true filters on the ontology's preferred prefix. An ontology that
    # declares none -- EHDAA2, EHDA, VHOG, AAO -- matches nothing, so the flag
    # silently turns every search into zero hits rather than scoping it.
    prefix = cfg.get("preferredPrefix")
    return {
        "label_property": cfg.get("labelProperty"),
        "synonym_properties": cfg.get("synonymProperties") or [],
        "definition_properties": cfg.get("definitionProperties") or [],
        "uses_ols4_defaults": not (cfg.get("synonymProperties") or []),
        "preferred_prefix": prefix,
        "supports_local": bool(prefix),
    }


def lexical(
    t: Transport,
    query: str,
    ontology: str,
    probes: tuple[str, ...] = ("exact", "stemmed"),
    rows: int = DEFAULT_ROWS,
    config: dict | None = None,
) -> dict:
    """Run the requested probes for one query string and merge the hits.

    Each hit records every probe that found it, that probe's rank, and -- for
    the exact probe -- exactly which fields matched. Nothing is filtered,
    reordered or selected.
    """
    unknown = [p for p in probes if p not in PROBES]
    if unknown:
        raise ValueError(f"unknown probe(s): {unknown}; expected any of {list(PROBES)}")

    cfg = config if config is not None else search_config(t, ontology)
    local = cfg.get("supports_local", True)

    by_curie: dict[str, dict] = {}
    found: dict[str, dict[str, dict]] = {}
    probe_info: dict[str, dict] = {}

    def record(probe: str, docs: list[dict], num_found: int, query_fields: str | None) -> None:
        probe_info[probe] = {
            "query_fields": query_fields,
            "exact": probe == "exact",
            "num_found": num_found,
            "returned": len(docs),
            "truncated": len(docs) < num_found,
        }
        for rank, d in enumerate(docs, start=1):
            curie = d.get("obo_id")
            if not curie:
                continue
            by_curie.setdefault(curie, d)
            entry: dict = {"rank": rank}
            if probe == "exact":
                entry["matched_fields"] = _matched_fields(d, query)
            found.setdefault(curie, {})[probe] = entry

    # "definition" is defined as the default search minus the stemmed set, so it
    # needs the stemmed result whether or not the caller asked for that probe.
    need_stemmed = "stemmed" in probes or "definition" in probes
    stemmed_curies: set[str] = set()

    if "exact" in probes:
        r = _search(t, query, ontology, "exact", rows, local)
        record("exact", r["docs"], r["num_found"], LEXICAL_QUERY_FIELDS)

    if need_stemmed:
        r = _search(t, query, ontology, "stemmed", rows, local)
        stemmed_curies = {d["obo_id"] for d in r["docs"] if d.get("obo_id")}
        if "stemmed" in probes:
            record("stemmed", r["docs"], r["num_found"], LEXICAL_QUERY_FIELDS)

    if "definition" in probes:
        r = _search(t, query, ontology, "definition", rows, local)
        defonly = [d for d in r["docs"] if d.get("obo_id") not in stemmed_curies]
        # num_found is for the default search as a whole; the subtraction is
        # done on what came back, so this count is of the returned page only.
        record("definition", defonly, len(defonly), None)

    hits = [h for c, d in by_curie.items() if (h := _to_hit(d, found[c]))]
    return {
        "query": query,
        "ontology": ontology,
        "search_config": cfg,
        "scoped_locally": local,
        "probes": probe_info,
        "total": len(hits),
        "hits": [h.as_dict() for h in hits],
    }


def linked_entities(t: Transport, ontology: str, curie: str) -> dict[str, dict]:
    """OLS4 v2's resolution of every CURIE a term references, keyed by CURIE.

    This is what the OLS web front end uses to turn an xref string into a
    clickable link: it supplies a resolvable URL and names the registry it came
    from (GO's db-xrefs.yaml or bioregistry). Neither the v1 API nor Ubergraph
    has an equivalent.
    """
    from .curies import to_iri

    try:
        doc = t.ols4_v2_class(ontology, to_iri(curie))
    except Exception as exc:  # enrichment, not the point of the command
        return {"__error__": {"message": str(exc)}}
    out = {}
    for key, val in (doc.get("linkedEntities") or {}).items():
        labels = val.get("label") or []
        out[key] = {
            "label": labels[0] if isinstance(labels, list) and labels else None,
            "url": val.get("url"),
            "registry": val.get("source"),
            "defined_by": val.get("definedBy"),
        }
    return out


def neighbours(
    t: Transport,
    ontology: str,
    curie: str,
    predicates: tuple[str, ...] = (),
    target_ontology: str | None = None,
) -> dict:
    """The one-hop neighbourhood of a term, from OLS4.

    Asserted direct relations in both directions, with predicate and node
    labels resolved. This is the way to get relations for an ontology Ubergraph
    does not hold -- EHDAA2's link to HsapDv (`existence starts during or
    after` -> Carnegie stage 09) is only visible here.

    Two endpoints, because neither alone is correct:

    * **Outgoing** comes from the v2 class record's ``relatedTo``, which keeps
      every OWL restriction with its ``owl:onProperty`` intact. The v1 term
      graph deduplicates edges by source and target, so a term asserting two
      predicates against the *same* target silently loses one of them.
      ``EHDAA2:0001570 pronephros`` is CS09-to-CS09 in the released OWL and
      reads through v1 as CS09-with-no-end -- an annotation twenty stages too
      late would pass. Verified live 2026-10-09: v1 returns only RO:0002496,
      v2 returns both RO:0002496 and RO:0002497.
    * **Incoming** has no v2 equivalent -- ``linksTo`` is outgoing and carries
      no predicate -- so it still comes from the v1 graph, and still carries
      v1's deduplication. That limitation is reported in ``warnings`` rather
      than hidden.

    Complementary to `relations` rather than a substitute: this is one hop and
    asserted, where Ubergraph gives inference closure. Neither offers what the
    other does.
    """
    from .curies import to_curie, to_iri

    iri = to_iri(curie)
    warnings: list[str] = []
    wanted = {to_iri(p) if ":" in p else p for p in predicates}

    def keep(pred_iri: str, other_curie: str) -> bool:
        if wanted and pred_iri not in wanted:
            return False
        return not (
            target_ontology
            and not other_curie.lower().startswith(target_ontology.lower() + ":")
        )

    # ---- outgoing, from v2 -------------------------------------------------
    out: dict[str, list[dict]] = {}
    label = None
    try:
        v2 = t.ols4_v2_class(ontology, iri)
    except Exception as exc:  # reported in warnings, not swallowed
        v2 = {}
        warnings.append(
            f"the v2 class record for {curie} was unavailable ({exc}); outgoing "
            "relations fall back to the v1 term graph, which drops one edge when "
            "two predicates share a target"
        )
    else:
        linked = v2.get("linkedEntities") or {}

        def _label(entity_iri: str) -> str | None:
            labs = (linked.get(entity_iri) or {}).get("label")
            if isinstance(labs, list):
                return labs[0] if labs else None
            return labs

        label = _label(iri) or (
            v2.get("label")[0] if isinstance(v2.get("label"), list) else v2.get("label")
        )
        for rel in v2.get("relatedTo") or []:
            pred_iri = rel.get("property")
            value = rel.get("value")
            if not pred_iri or not value:
                continue
            other = to_curie(value)
            if not keep(pred_iri, other):
                continue
            pred = _label(pred_iri) or to_curie(pred_iri)
            entry = {
                "curie": other,
                "label": _label(value),
                "predicate": to_curie(pred_iri),
            }
            row = out.setdefault(pred, [])
            if entry not in row:
                row.append(entry)

    # ---- incoming, from v1 -------------------------------------------------
    doc = t.ols4_graph(ontology, iri)
    labels = {n["iri"]: n.get("label") for n in doc.get("nodes") or []}
    label = label or labels.get(iri)
    inc: dict[str, list[dict]] = {}
    v1_out: dict[str, list[dict]] = {}
    for e in doc.get("edges") or []:
        pred_iri = e.get("uri") or ""
        pred = e.get("label") or pred_iri
        if e.get("target") == iri and e.get("source") != iri:
            other, bucket = e.get("source"), inc
        elif e.get("source") == iri:
            other, bucket = e.get("target"), v1_out
        else:
            continue  # an edge between two neighbours, not involving the term
        other_curie = to_curie(other)
        if not keep(pred_iri, other_curie):
            continue
        entry = {
            "curie": other_curie,
            "label": labels.get(other),
            "predicate": to_curie(pred_iri) if pred_iri else None,
        }
        row = bucket.setdefault(pred, [])
        if entry not in row:
            row.append(entry)

    if inc:
        warnings.append(
            "incoming relations come from OLS4's v1 term graph, which has no v2 "
            "equivalent. v1 deduplicates edges by source and target, so if two "
            "predicates point at this term from the same source, only one is "
            "shown. Outgoing relations are not affected."
        )
    # Visible proof that the v2 route recovered something, rather than a claim.
    n_v2 = sum(len(v) for v in out.values())
    n_v1 = sum(len(v) for v in v1_out.values())
    if out and n_v2 > n_v1:
        warnings.append(
            f"v2 reports {n_v2} outgoing relations where the v1 term graph reports "
            f"{n_v1}; the difference is edges v1 drops when two predicates share a "
            "target"
        )
    if not out and v1_out:
        out = v1_out

    return {
        "curie": curie,
        "ontology": ontology,
        "label": label,
        "predicates": list(predicates) or None,
        "target_ontology": target_ontology,
        "outgoing": {k: sorted(v, key=lambda d: d["curie"]) for k, v in sorted(out.items())},
        "incoming": {k: sorted(v, key=lambda d: d["curie"]) for k, v in sorted(inc.items())},
        "external_targets": sorted(
            {
                d["curie"].split(":")[0]
                for v in out.values()
                for d in v
                if not d["curie"].startswith(curie.split(":")[0] + ":")
            }
        ),
        "warnings": warnings,
    }


# The server clamps `size` to this; asking for more is silently reduced.
PAGE_SIZE = 1000
DEFAULT_MAX_TERMS = 1000

RELATIONS = {
    ("up", False): "ancestors",
    ("up", True): "hierarchicalAncestors",
    ("down", False): "descendants",
    ("down", True): "hierarchicalDescendants",
}


def _hierarchy_page(t: Transport, ontology: str, iri: str, relation: str) -> dict:
    """All pages of one hierarchy relation, up to DEFAULT_MAX_TERMS."""
    terms: dict[str, list[str]] = {}
    total = 0
    page = 0
    while True:
        doc = t.ols4_hierarchy(ontology, iri, relation, PAGE_SIZE, page)
        total = (doc.get("page") or {}).get("totalElements", 0)
        for term in (doc.get("_embedded") or {}).get("terms") or []:
            curie = term.get("obo_id") or term.get("short_form")
            if not curie:
                continue
            labels = terms.setdefault(curie, [])
            if (lab := term.get("label")) and lab not in labels:
                labels.append(lab)
        page += 1
        if len(terms) >= total or len(terms) >= DEFAULT_MAX_TERMS or page > 20:
            break
    return {"terms": terms, "total": total}


def hierarchy(
    t: Transport,
    ontology: str,
    curie: str,
    direction: str = "up",
    subsumption_only: bool = False,
) -> dict:
    """Ancestors or descendants of a term, from OLS4.

    The route for ontologies Ubergraph does not hold. Two flavours are fetched,
    because the difference is the thing people get wrong: `ancestors` follows
    subClassOf alone, `hierarchicalAncestors` also follows the ontology's
    hierarchical properties (part_of and friends). For EHDAA2 liver that is 8
    against 19 going up, and 0 against 26 going down -- a subsumption-only
    answer would say the liver has no parts.

    Note `page.totalPages` from the API is unusable (it repeats totalElements),
    so paging is driven from totalElements.
    """
    from .curies import to_iri

    if direction not in ("up", "down"):
        raise ValueError("direction must be 'up' or 'down'")
    iri = to_iri(curie)

    sub = _hierarchy_page(t, ontology, iri, RELATIONS[(direction, False)])
    result = {
        "curie": curie,
        "ontology": ontology,
        "direction": direction,
        "subsumption": {
            "relation": RELATIONS[(direction, False)],
            "total": sub["total"],
            "returned": len(sub["terms"]),
            "truncated": len(sub["terms"]) < sub["total"],
            "terms": [{"curie": c, "labels": v} for c, v in sorted(sub["terms"].items())],
        },
    }
    if subsumption_only:
        return result

    hier = _hierarchy_page(t, ontology, iri, RELATIONS[(direction, True)])
    extra = {c: v for c, v in hier["terms"].items() if c not in sub["terms"]}
    result["hierarchical"] = {
        "relation": RELATIONS[(direction, True)],
        "total": hier["total"],
        "returned": len(hier["terms"]),
        "truncated": len(hier["terms"]) < hier["total"],
        "reached_only_via_other_relations": [
            {"curie": c, "labels": v} for c, v in sorted(extra.items())
        ],
    }
    return result
