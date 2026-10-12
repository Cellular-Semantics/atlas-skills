"""Graph primitives against Ubergraph.

Bounding is the thing this module exists to get right. Ubergraph holds ~45
ontologies in one store, and an unbounded pattern scans all of them. Measured on
one query returning the same 4 rows: graph-scoped 0.65-1.34s; unscoped 76s;
unscoped with a trailing FILTER(STRSTARTS(STR(?s), "...UBERON_")) timed out at
120s. The prefix filter is *slower than no filter at all*, because it is a
post-filter over a result set the engine has already built in full.

So, three mechanisms, in this order:

1. Bind the seed set with VALUES in the first triple pattern.
2. Restrict output to one ontology with a joined ``rdfs:isDefinedBy`` triple in
   the ontology graph. The upstream README notes this is much faster than a URI
   prefix filter, and unlike the prefix filter it is a join.
3. Scope to a per-ontology named graph. These hold *asserted* axioms only, so
   they are right for annotations and label surveys and wrong for closure.

Nothing here scores or selects. Every function returns annotated evidence.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .curies import defined_by_iri, to_curie, to_iri
from .transport import Transport, sparql_rows

ONTOLOGY_GRAPH = "http://reasoner.renci.org/ontology"
NONREDUNDANT_GRAPH = "http://reasoner.renci.org/nonredundant"
REDUNDANT_GRAPH = "http://reasoner.renci.org/redundant"
IC_PREDICATE = "http://reasoner.renci.org/vocab/normalizedInformationContent"

PREFIXES = """
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX owl: <http://www.w3.org/2002/07/owl#>
PREFIX oio: <http://www.geneontology.org/formats/oboInOwl#>
PREFIX obo: <http://purl.obolibrary.org/obo/>
PREFIX skos: <http://www.w3.org/2004/02/skos/core#>
PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
"""

# In the redundant graph every predicate except rdfs:subClassOf is shorthand for
# an existential restriction, so these can be used as plain predicates.
PREDICATES = {
    "subClassOf": "rdfs:subClassOf",
    "part_of": "obo:BFO_0000050",
    "has_part": "obo:BFO_0000051",
    "overlaps": "obo:RO_0002131",
    "develops_from": "obo:RO_0002202",
    "in_taxon": "obo:RO_0002162",
}

DEFAULT_ANCESTOR_PREDICATES = ("subClassOf", "part_of")

# 82 seeds returned in 0.9s; 718 timed out at 120s. Fail loudly rather than hang.
MAX_SEEDS = 300


class SeedLimitExceeded(ValueError):
    pass


def _pred(name: str) -> str:
    """Resolve a predicate to a SPARQL term.

    PREDICATES is an alias table, not an allowlist. A CURIE is passed straight
    through, so any RO predicate is reachable -- `connected to`, `attaches to`,
    the existence predicates -- without the table having to know about it. A
    bare word must be a known alias, so a typo like 'part-of' still fails
    loudly instead of querying an IRI that does not exist.
    """
    if name in PREDICATES:
        return PREDICATES[name]
    if ":" in name and not name.startswith(("http://", "https://")):
        return f"<{to_iri(name)}>"
    if name.startswith(("http://", "https://")):
        return f"<{name}>"
    raise ValueError(
        f"unknown predicate {name!r}: not one of the aliases {sorted(PREDICATES)}, "
        "and not a CURIE. Pass a CURIE such as RO:0002170 to use any other "
        "predicate; `oq term <CURIE> -o <ontology>` lists the predicates a term "
        "actually carries, with their CURIEs."
    )


def _values(curies: list[str]) -> str:
    return " ".join(f"<{to_iri(c)}>" for c in curies)


@dataclass
class Ubergraph:
    transport: Transport
    _graphs: list[str] | None = field(default=None, repr=False)

    def query(self, body: str) -> list[dict[str, str]]:
        return sparql_rows(self.transport.sparql(PREFIXES + body))

    # ---- ontology bookkeeping -------------------------------------------

    def named_graphs(self) -> list[str]:
        if self._graphs is None:
            rows = self.query("SELECT DISTINCT ?g WHERE { GRAPH ?g { ?s ?p ?o } }")
            self._graphs = [r["g"] for r in rows]
        return self._graphs

    def graph_for(self, ontology: str) -> str | None:
        """Per-ontology asserted-axiom graph, or None if absent from Ubergraph."""
        ont = ontology.lower()
        for g in self.named_graphs():
            if f"/{ont}." in g or f"/{ont}-base" in g:
                return g
        return None

    def has_ontology(self, ontology: str) -> bool:
        return self.graph_for(ontology) is not None

    # ---- common ancestors ------------------------------------------------

    def common_ancestors(
        self,
        seeds: list[str],
        target_ontology: str,
        predicates: tuple[str, ...] = DEFAULT_ANCESTOR_PREDICATES,
    ) -> dict:
        """Subsumers of a seed set, restricted to one ontology.

        Annotated with how many seeds each covers, which seeds it misses, and
        Ubergraph's precomputed normalized information content. No winner is
        chosen and no coverage threshold is applied.

        Two things callers get wrong. First, the part_of leg is not optional:
        over rdfs:subClassOf alone, cornea + conjunctiva yields nothing better
        than "anatomical structure", because they are *parts of* the ocular
        surface region rather than subclasses of it. Second, requiring full
        coverage is brittle -- "zone of skin" has the highest IC of any candidate
        for the skin-zone seed set and covers 81 of 82 seeds, so it would be
        dropped by a 100% filter.

        The redundant graph includes reflexive subclass relations, so a seed can
        appear among its own ancestors. That is correct: if one seed subsumes the
        rest, it is the answer.
        """
        if not seeds:
            raise ValueError("no seeds given")
        if len(seeds) > MAX_SEEDS:
            raise SeedLimitExceeded(
                f"{len(seeds)} seeds exceeds the {MAX_SEEDS} limit; partition the "
                "set by sense first (measured: 718 seeds times out)"
            )

        # Deliberately stricter than _pred. common-ancestors ranks its output by
        # information content, and IC is only comparable across rows because every
        # row came from the same traversal. An arbitrary predicate here would make
        # the number meaningless, so this one keeps the curated set.
        unknown = [p for p in predicates if p not in PREDICATES]
        if unknown:
            raise ValueError(
                f"common-ancestors takes only the curated predicates "
                f"{sorted(PREDICATES)}; got {unknown}. This is not the same rule as "
                "`relations`, which accepts any predicate CURIE: the traversal here "
                "is fixed so that information content stays comparable between rows."
            )
        pvals = " ".join(_pred(p) for p in predicates)
        defined_by = defined_by_iri(target_ontology)

        pairs = self.query(f"""
SELECT ?anc ?x WHERE {{
  VALUES ?x {{ {_values(seeds)} }}
  VALUES ?p {{ {pvals} }}
  GRAPH <{REDUNDANT_GRAPH}> {{ ?x ?p ?anc . }}
  GRAPH <{ONTOLOGY_GRAPH}> {{
    ?anc rdfs:isDefinedBy <{defined_by}> .
    FILTER NOT EXISTS {{ ?anc owl:deprecated true }}
  }}
}}""")

        covered: dict[str, set[str]] = {}
        for r in pairs:
            covered.setdefault(to_curie(r["anc"]), set()).add(to_curie(r["x"]))

        details = self._labels_and_ic(sorted(covered)) if covered else {}

        seedset = set(seeds)
        out = []
        for anc, seen in covered.items():
            d = details.get(anc, {})
            out.append(
                {
                    "curie": anc,
                    "labels": d.get("labels", []),
                    "ic": d.get("ic"),
                    "covers": len(seen),
                    "of_seeds": len(seedset),
                    "missing_seeds": sorted(seedset - seen),
                    # The redundant graph is reflexive, so each seed subsumes itself.
                    # Flagged rather than dropped: if one seed subsumes all the
                    # others it is a legitimate answer.
                    "is_seed": anc in seedset,
                }
            )
        # Most specific first by IC. This is an ordering of evidence, not a
        # verdict: read the shape of the IC column and the gaps in it.
        out.sort(key=lambda r: (-r["covers"], -(r["ic"] if r["ic"] is not None else -1)))
        return {
            "seeds": seeds,
            "target_ontology": target_ontology,
            "predicates": list(predicates),
            "subsumers": out,
        }

    def _labels_and_ic(self, curies: list[str]) -> dict[str, dict]:
        rows = self.query(f"""
SELECT ?s ?label ?ic WHERE {{
  VALUES ?s {{ {_values(curies)} }}
  GRAPH <{ONTOLOGY_GRAPH}> {{
    ?s rdfs:label ?label .
    OPTIONAL {{ ?s <{IC_PREDICATE}> ?ic }}
  }}
}}""")
        out: dict[str, dict] = {}
        for r in rows:
            # Some terms carry two rdfs:label values (GO:0008150, GO:0110165),
            # so labels is a list.
            entry = out.setdefault(to_curie(r["s"]), {"labels": [], "ic": None})
            if r["label"] not in entry["labels"]:
                entry["labels"].append(r["label"])
            if r.get("ic") is not None and entry["ic"] is None:
                entry["ic"] = round(float(r["ic"]), 2)
        return out

    # ---- relations -------------------------------------------------------

    def relations(
        self,
        curie: str,
        predicate: str = "part_of",
        direction: str = "in",
        target_ontology: str | None = None,
        graph: str = "redundant",
    ) -> dict:
        """Terms standing in a named relation to ``curie``.

        ``direction="in"`` asks what points at the term (what is part_of this
        region); ``"out"`` asks what the term points at. Cross-ontology works:
        part_of retina returns 55 CL terms. located_in (RO:0001025) returns
        nothing for CL->Uberon in practice -- part_of carries that relationship.

        ``graph`` chooses between Ubergraph's two inference graphs, and the
        difference is large. For ``UBERON:0002240 develops_from`` out:
        nonredundant gives one edge (posterior neural tube), redundant gives 29,
        mostly upper-ontology terms reached through the closure. Direct first,
        closure only when the direct edge leads somewhere unusable.
        """
        if direction not in ("in", "out"):
            raise ValueError("direction must be 'in' or 'out'")
        try:
            graph_iri = {
                "redundant": REDUNDANT_GRAPH,
                "nonredundant": NONREDUNDANT_GRAPH,
            }[graph]
        except KeyError:
            raise ValueError("graph must be 'redundant' or 'nonredundant'") from None
        p = _pred(predicate)
        pattern = f"?other {p} ?anchor ." if direction == "in" else f"?anchor {p} ?other ."
        restrict = ""
        if target_ontology:
            restrict = f"?other rdfs:isDefinedBy <{defined_by_iri(target_ontology)}> ."
        rows = self.query(f"""
SELECT ?other ?label WHERE {{
  VALUES ?anchor {{ <{to_iri(curie)}> }}
  GRAPH <{graph_iri}> {{ {pattern} }}
  GRAPH <{ONTOLOGY_GRAPH}> {{
    {restrict}
    ?other rdfs:label ?label .
    FILTER NOT EXISTS {{ ?other owl:deprecated true }}
  }}
}}""")
        seen: dict[str, list[str]] = {}
        for r in rows:
            seen.setdefault(to_curie(r["other"]), []).append(r["label"])
        return {
            "anchor": curie,
            "predicate": predicate,
            "direction": direction,
            "target_ontology": target_ontology,
            "graph": graph,
            "total": len(seen),
            "terms": [{"curie": c, "labels": ls} for c, ls in sorted(seen.items())],
        }

    # ---- term detail -----------------------------------------------------

    def term(self, curie: str, ontology: str) -> dict:
        """One term's asserted annotations plus pruned relations."""
        res = self.terms([curie], ontology)
        block = res["terms"][0]
        return {
            "curie": block["curie"],
            "ontology": ontology,
            "annotations": block["annotations"],
            "relations": block["relations"],
            "warnings": res["warnings"],
        }

    def terms(self, curies: list[str], ontology: str) -> dict:
        """Asserted annotations plus pruned relations, for one or many terms.

        Adjudication is comparison, not lookup. What separates a shortlist is
        usually a contrast between candidates -- this one is part of the kidney
        and that one of the collecting duct system; this one carries a taxon
        restriction the record contradicts -- and a contrast is visible when the
        candidates are side by side and has to be reconstructed when they are
        not. So the whole shortlist is one call, answered from one query.

        Annotations come from the per-ontology asserted graph. Relations come
        from the nonredundant graph, which is pruned but *not* free of closure
        noise -- UBERON:0010409 carries fifteen "existence starts during or
        after" edges there. The noise is reported rather than guessed at.

        Each block says whether anything was found for that CURIE. Asked one at
        a time, "this term has no further axioms" and "this term is not in the
        ontology you named" produce the same empty-looking answer; one is weak
        evidence and the other means the question was wrong.
        """
        if not curies:
            raise ValueError("no curies given")
        warnings: list[str] = []
        graph = self.graph_for(ontology)
        values = _values(curies)

        annotations: dict[str, dict[str, list[str]]] = {c: {} for c in curies}
        if graph is None:
            warnings.append(
                f"{ontology} is not in Ubergraph; asserted annotations unavailable. "
                "An empty result here is the backend not holding this ontology, "
                "not a term without axioms."
            )
        else:
            for r in self.query(f"""
SELECT ?s ?p ?v WHERE {{
  VALUES ?s {{ {values} }}
  GRAPH <{graph}> {{ ?s ?p ?v . FILTER(isLiteral(?v)) }}
}}"""):
                annotations[to_curie(r["s"])].setdefault(_short(r["p"]), []).append(r["v"])

        rows = self.query(f"""
SELECT ?s ?p ?o ?plabel ?olabel WHERE {{
  VALUES ?s {{ {values} }}
  GRAPH <{NONREDUNDANT_GRAPH}> {{ ?s ?p ?o . FILTER(isIRI(?o)) }}
  OPTIONAL {{ GRAPH ?g1 {{ ?o rdfs:label ?olabel }} }}
  OPTIONAL {{ GRAPH ?g2 {{ ?p rdfs:label ?plabel }} }}
}}""")
        # Keyed by the predicate's CURIE, not its label. The label alone is a
        # dead end: a caller who sees "connected to" here has nothing to pass to
        # `relations -p`. This is the discovery half of that loop.
        rels: dict[str, dict[str, dict]] = {c: {} for c in curies}
        for r in rows:
            subj = to_curie(r["s"])
            pcurie = to_curie(r["p"])
            obj = to_curie(r["o"])
            entry = rels[subj].setdefault(
                pcurie, {"predicate": pcurie, "label": r.get("plabel"), "terms": {}}
            )
            if entry["label"] is None and r.get("plabel"):
                entry["label"] = r["plabel"]
            t = entry["terms"].setdefault(obj, {"curie": obj, "labels": []})
            if (lab := r.get("olabel")) and lab not in t["labels"]:
                t["labels"].append(lab)

        warnings.append(
            "relations come from the nonredundant graph, which still contains "
            "closure noise; treat these as inferred rather than asserted"
        )
        empty = [c for c in curies if not annotations[c] and not rels[c]]
        if empty:
            # Three different situations produce the same empty block, and they
            # call for different responses, so name them rather than leaving the
            # caller to read silence.
            if graph is None:
                why = (
                    f"{ontology} is not in Ubergraph at all, so this is silence "
                    "from the backend. Try `oq neighbours`, which reads OLS4."
                )
            else:
                mismatched = sorted(
                    {c.split(":")[0] for c in empty if not c.lower().startswith(ontology.lower())}
                )
                why = (
                    f"{ontology} is in Ubergraph, so either these terms are not in "
                    "it or they carry no axioms."
                )
                if mismatched:
                    why += (
                        f" Prefixes seen here that are not {ontology}: "
                        f"{', '.join(mismatched)}. Pass the ontology each CURIE "
                        "belongs to."
                    )
            warnings.append(f"nothing found for {', '.join(empty)}. {why}")

        blocks = []
        for c in curies:
            labels = annotations[c].get("label") or []
            blocks.append({
                "curie": c,
                "label": labels[0] if labels else None,
                "found": bool(annotations[c] or rels[c]),
                "annotations": annotations[c],
                "relations": [
                    {
                        "predicate": e["predicate"],
                        "label": e["label"],
                        "terms": sorted(e["terms"].values(), key=lambda d: d["curie"]),
                    }
                    for _, e in sorted(
                        rels[c].items(), key=lambda kv: (kv[1]["label"] or "", kv[0])
                    )
                ],
            })
        return {"ontology": ontology, "terms": blocks, "warnings": warnings}

    # ---- cross-references ------------------------------------------------

    def xrefs(self, curie: str) -> dict:
        """Database cross-references, resolved against the store where possible.

        In OBO ontologies an xref is a plain literal -- `oio:hasDbXref
        "MA:0002486"` -- not a link and not an axiom. But Ubergraph holds the
        target ontologies too, so the literal can be joined back to a real class
        and given a label. Where the join fails, the xref points somewhere
        Ubergraph does not hold, which is itself worth knowing.

        SKOS mappings are returned separately, because they are assertions the
        source ontology actually made rather than something reconstructed here.
        Most OBO ontologies have none; MONDO carries plenty.
        """
        u = f"<{to_iri(curie)}>"

        # Two bound queries rather than one with a BIND inside an OPTIONAL. The
        # BIND form looks tidier and is a trap: Blazegraph is free to evaluate
        # `?target rdfs:label ?label` before the BIND, which scans every label in
        # the store. It read 2.4GB before dying when this was written that way.
        literals = [
            r["xref"]
            for r in self.query(f"""
SELECT ?xref WHERE {{
  VALUES ?s {{ {u} }}
  GRAPH <{ONTOLOGY_GRAPH}> {{ ?s oio:hasDbXref ?xref }}
}}""")
        ]

        xrefs: dict[str, dict] = {x: {"value": x, "resolved": None, "labels": []} for x in literals}
        targets = {}
        for x in literals:
            try:
                targets[to_iri(x)] = x
            except ValueError:
                continue  # not a CURIE at all, e.g. a free-text or URL xref
        if targets:
            for r in self.query(f"""
SELECT ?target ?label ?src WHERE {{
  VALUES ?target {{ {" ".join(f"<{i}>" for i in targets)} }}
  GRAPH <{ONTOLOGY_GRAPH}> {{ ?target rdfs:label ?label ; rdfs:isDefinedBy ?src }}
}}"""):
                entry = xrefs[targets[r["target"]]]
                entry["resolved"] = {
                    "curie": to_curie(r["target"]),
                    "defined_by": r.get("src"),
                }
                if (lab := r.get("label")) and lab not in entry["labels"]:
                    entry["labels"].append(lab)

        maps = self.query(f"""
SELECT ?p ?o WHERE {{
  VALUES ?s {{ {u} }}
  VALUES ?p {{ skos:exactMatch skos:closeMatch skos:broadMatch skos:narrowMatch
              skos:relatedMatch owl:equivalentClass }}
  GRAPH <{ONTOLOGY_GRAPH}> {{ ?s ?p ?o . FILTER(isIRI(?o)) }}
}}""")
        mapped = {to_curie(r["o"]) for r in maps}
        labels = self._labels_and_ic(sorted(mapped)) if mapped else {}
        mappings: dict[str, list[dict]] = {}
        for r in maps:
            target = to_curie(r["o"])
            bucket = mappings.setdefault(_short(r["p"]), [])
            if not any(m["curie"] == target for m in bucket):
                bucket.append({"curie": target, "labels": labels.get(target, {}).get("labels", [])})

        return {
            "curie": curie,
            "xrefs": sorted(xrefs.values(), key=lambda d: d["value"]),
            "unresolved": sorted(x["value"] for x in xrefs.values() if not x["resolved"]),
            "mappings": mappings,
        }

    def crosswalk(self, xref: str, target_ontology: str | None = None) -> dict:
        """Which terms in the store cross-reference this identifier.

        The reverse of `xrefs`, and the way to reach an ontology Ubergraph does
        not hold. EHDAA2 is not in Ubergraph, but Uberon cross-references it
        extensively, so EHDAA2:0000997 resolves to UBERON:0002107 (liver) in
        about half a second.

        The literals are typed ``xsd:string``, and Blazegraph does not treat a
        plain literal as equal to one. Matching ``"EHDAA2:0000997"`` returns
        zero rows -- a silent wrong answer, not an error. Matching
        ``"EHDAA2:0000997"^^xsd:string`` returns the hit. The alternative,
        ``FILTER(STR(?x) = ...)``, is correct but unbound: measured at 69s
        against 0.56s for the typed form.
        """
        if '"' in xref or "\\" in xref:
            raise ValueError(f"not a usable identifier: {xref!r}")
        restrict = (
            f"?s rdfs:isDefinedBy <{defined_by_iri(target_ontology)}> ." if target_ontology else ""
        )
        rows = self.query(f"""
SELECT ?s ?label ?src WHERE {{
  GRAPH <{ONTOLOGY_GRAPH}> {{
    ?s oio:hasDbXref "{xref}"^^xsd:string .
    {restrict}
    ?s rdfs:label ?label ; rdfs:isDefinedBy ?src .
    FILTER NOT EXISTS {{ ?s owl:deprecated true }}
  }}
}}""")
        found: dict[str, dict] = {}
        for r in rows:
            entry = found.setdefault(
                to_curie(r["s"]), {"curie": to_curie(r["s"]), "labels": [], "defined_by": r["src"]}
            )
            if r["label"] not in entry["labels"]:
                entry["labels"].append(r["label"])
        return {
            "xref": xref,
            "target_ontology": target_ontology,
            "total": len(found),
            "terms": sorted(found.values(), key=lambda d: d["curie"]),
        }

    # ---- cohort surveys --------------------------------------------------

    def cohort(
        self,
        ontology: str,
        sibling_of: str | None = None,
        label_contains: str | None = None,
        text_contains: str | None = None,
        under: str | None = None,
        limit: int = 500,
    ) -> dict:
        """Survey a set of terms, by naming convention or by where they sit.

        ``label_contains`` surveys an ontology for a wording pattern: one query
        over hsapdv for labels containing "week" returns 30 terms, all of the
        form "9th week post-fertilization stage", none of which carry any
        synonym at all. No amount of trying "12 pcw" will ever hit one. It
        matches ``rdfs:label`` and nothing else, deliberately -- for reading a
        convention off real labels, a synonym would be noise.

        ``text_contains`` matches the label *or any synonym*, and reports which
        field matched. Use it when you are looking for a term rather than for a
        convention, because the string a record carries is very often not the
        label. ``UBERON:0006073`` is labelled "thoracic region of vertebral
        column" and carries "thoracic spine" only as an exact synonym, so a
        label-only filter misses it -- and this is the route a caller reaches
        for *after* the direct lexical probe has already failed, which is the
        worst possible place for a silent miss.

        ``sibling_of`` returns the co-children of a term's direct parents.

        ``under`` restricts to terms inside a region, and composes with either
        text filter. This is the route for a record whose own text is ambiguous
        but whose other fields say where in the body it came from: "cortex"
        matches 150 Uberon labels, and the handful inside the kidney are the
        ones such a record means.

        The traversal for ``under`` is subClassOf *and* part_of, and the part_of
        leg is not optional: ``cortex of kidney`` is part of the kidney, not a
        subclass of it, so a subsumption-only reading returns nothing here. It
        reads the redundant graph, which is reflexive over subClassOf, so the
        anchor comes back in its own cohort. That row is flagged ``is_anchor``
        rather than dropped.
        """
        if label_contains is not None and text_contains is not None:
            raise ValueError("give at most one of label_contains or text_contains")
        filters = [label_contains, text_contains]
        if sibling_of is not None and under is not None:
            raise ValueError("sibling_of and under cannot be combined")
        if sibling_of is not None and any(f is not None for f in filters):
            raise ValueError("sibling_of cannot be combined with a text filter")
        if sibling_of is None and under is None and not any(f is not None for f in filters):
            raise ValueError(
                "give at least one of sibling_of, label_contains, text_contains or under"
            )
        graph = self.graph_for(ontology)
        if graph is None:
            raise ValueError(f"{ontology} is not in Ubergraph")

        # Only the label-or-synonym path needs the matched property bound. The
        # other bodies are left byte-identical to what they were, because the
        # test cassette keys fixtures on the exact query string: gratuitously
        # reformatting a working query silently invalidates its recording.
        if text_contains is not None:
            needle = text_contains.lower()
            match_block = f"""    VALUES ?field {{ rdfs:label oio:hasExactSynonym oio:hasBroadSynonym
                     oio:hasNarrowSynonym oio:hasRelatedSynonym }}
    ?s ?field ?matched .
    FILTER(CONTAINS(LCASE(STR(?matched)), "{needle}"))"""
            select = "?s ?label ?field ?matched"
        else:
            match_block = (
                f'    FILTER(CONTAINS(LCASE(STR(?label)), "{label_contains.lower()}"))'
                if label_contains is not None
                else ""
            )
            select = "?s ?label"

        if under is not None:
            # Anchor bound first, so the closure scan is bounded by it rather
            # than by the text pattern. In the redundant graph part_of is
            # carried as a plain predicate, shorthand for the existential.
            body = f"""
SELECT {select} WHERE {{
  VALUES ?anchor {{ <{to_iri(under)}> }}
  VALUES ?p {{ rdfs:subClassOf obo:BFO_0000050 }}
  GRAPH <{REDUNDANT_GRAPH}> {{ ?s ?p ?anchor . }}
  GRAPH <{graph}> {{
    ?s rdfs:label ?label .
    FILTER NOT EXISTS {{ ?s owl:deprecated true }}
{match_block}
  }}
}} LIMIT {limit}"""
        elif text_contains is not None:
            body = f"""
SELECT {select} WHERE {{
  GRAPH <{graph}> {{
    ?s rdfs:label ?label .
    FILTER NOT EXISTS {{ ?s owl:deprecated true }}
{match_block}
  }}
}} LIMIT {limit}"""
        elif label_contains is not None:
            body = f"""
SELECT ?s ?label WHERE {{
  GRAPH <{graph}> {{
    ?s rdfs:label ?label .
    FILTER(CONTAINS(LCASE(STR(?label)), "{label_contains.lower()}"))
    FILTER NOT EXISTS {{ ?s owl:deprecated true }}
  }}
}} LIMIT {limit}"""
        else:
            body = f"""
SELECT ?s ?label WHERE {{
  VALUES ?anchor {{ <{to_iri(sibling_of)}> }}
  GRAPH <{NONREDUNDANT_GRAPH}> {{
    ?anchor rdfs:subClassOf ?parent .
    ?s rdfs:subClassOf ?parent .
  }}
  GRAPH <{graph}> {{
    ?s rdfs:label ?label .
    FILTER NOT EXISTS {{ ?s owl:deprecated true }}
  }}
}} LIMIT {limit}"""

        rows = self.query(body)
        seen: dict[str, dict] = {}
        for r in rows:
            curie = to_curie(r["s"])
            e = seen.setdefault(curie, {"labels": [], "matched_fields": {}})
            if r["label"] not in e["labels"]:
                e["labels"].append(r["label"])
            if r.get("field"):
                field = _short(r["field"])
                if field != "label":
                    # oio:hasExactSynonym -> exact_synonym, matching lexical
                    field = re.sub(r"(?<!^)(?=[A-Z])", "_", field.replace("has", "", 1)).lower()
                matched = r.get("matched")
            else:
                # No ?field bound means the body filtered on rdfs:label itself.
                field, matched = "label", r["label"]
            vals = e["matched_fields"].setdefault(field, [])
            if matched and matched not in vals:
                vals.append(matched)

        terms = []
        for c, e in sorted(seen.items()):
            row = {"curie": c, "labels": e["labels"]}
            if label_contains is not None or text_contains is not None:
                row["matched_fields"] = e["matched_fields"]
            if c == under:
                row["is_anchor"] = True
            terms.append(row)
        return {
            "ontology": ontology,
            "sibling_of": sibling_of,
            "label_contains": label_contains,
            "text_contains": text_contains,
            "under": under,
            "total": len(seen),
            "truncated": len(rows) >= limit,
            "terms": terms,
        }


def _short(iri: str) -> str:
    for sep in ("#", "/"):
        if sep in iri:
            iri = iri.rsplit(sep, 1)[-1]
    return iri
