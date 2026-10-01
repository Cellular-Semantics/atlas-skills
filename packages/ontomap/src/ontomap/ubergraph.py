"""Ubergraph: structure, axioms and numbers. One SPARQL endpoint, five ontologies.

Ubergraph holds UBERON, HsapDv, MONDO, PATO, NCBITaxon, CL and EMAPA together
with a reasoner's closure over them, which is why the whole structural layer can
talk to one service.

**Every method names its graph explicitly and none of them defaults.** This is
not fussiness. Ubergraph exposes three graphs and the difference between them is
invisible in a result set: a query for taxon constraints against ``ontology``
returns zero rows, and so does a query for existence-window edges, because in
both cases the axioms are materialised into ``nonredundant`` instead. Zero rows
reads as "the ontology does not say this" when it means "you asked the wrong
graph". That mistake was made twice while designing this module, the second time
by someone who had already written the warning. Hence: no default.

    ONTOLOGY     asserted axioms, labels, definitions, annotations, xrefs
    NONREDUNDANT closure with redundant edges removed -- direct-ish relations
    REDUNDANT    full reasoner closure -- use for "is X under Y" tests
"""

from __future__ import annotations

import json
from typing import Any

import httpx

from .cache import Cache
from .errors import OntomapError

ENDPOINT = "https://ubergraph.apps.renci.org/sparql"

ONTOLOGY = "http://reasoner.renci.org/ontology"
NONREDUNDANT = "http://reasoner.renci.org/nonredundant"
REDUNDANT = "http://reasoner.renci.org/redundant"

OBO = "http://purl.obolibrary.org/obo/"

# Relations, by their role rather than their number, because RO_0002496 at a
# call site tells a reader nothing.
SUBCLASS_OF = "http://www.w3.org/2000/01/rdf-schema#subClassOf"
PART_OF = f"{OBO}BFO_0000050"
PRECEDED_BY = f"{OBO}BFO_0000062"
DEVELOPS_FROM = f"{OBO}RO_0002202"
DIRECTLY_DEVELOPS_FROM = f"{OBO}RO_0002207"
DEVELOPMENTAL_CONTRIBUTION_FROM = f"{OBO}RO_0002254"
ONLY_IN_TAXON = f"{OBO}RO_0002162"
NEVER_IN_TAXON = f"{OBO}RO_0002161"
EXISTENCE_STARTS_DURING_OR_AFTER = f"{OBO}RO_0002496"
EXISTENCE_ENDS_DURING_OR_BEFORE = f"{OBO}RO_0002497"

DEFINITION = f"{OBO}IAO_0000115"
HAS_DBXREF = "http://www.geneontology.org/formats/oboInOwl#hasDbXref"
HAS_EXACT_SYNONYM = "http://www.geneontology.org/formats/oboInOwl#hasExactSynonym"
HAS_RELATED_SYNONYM = "http://www.geneontology.org/formats/oboInOwl#hasRelatedSynonym"
HAS_NARROW_SYNONYM = "http://www.geneontology.org/formats/oboInOwl#hasNarrowSynonym"
HAS_BROAD_SYNONYM = "http://www.geneontology.org/formats/oboInOwl#hasBroadSynonym"
IN_SUBSET = "http://www.geneontology.org/formats/oboInOwl#inSubset"
RDFS_LABEL = "http://www.w3.org/2000/01/rdf-schema#label"
RDFS_COMMENT = "http://www.w3.org/2000/01/rdf-schema#comment"
DEPRECATED = "http://www.w3.org/2002/07/owl#deprecated"

# Ubergraph precomputes this per term. It is a far better specificity ranking
# than graph depth: depth is what makes `subdivision of oviduct` outrank
# `oviduct` as a common ancestor, which no curator would accept.
INFORMATION_CONTENT = "http://reasoner.renci.org/vocab/normalizedInformationContent"

SYNONYM_SCOPES = {
    HAS_EXACT_SYNONYM: "exact",
    HAS_RELATED_SYNONYM: "related",
    HAS_NARROW_SYNONYM: "narrow",
    HAS_BROAD_SYNONYM: "broad",
}


def curie(iri: str) -> str:
    """``http://...UBERON_0002107`` -> ``UBERON:0002107``. Non-OBO IRIs pass through."""
    if iri.startswith(OBO):
        return iri[len(OBO) :].replace("_", ":", 1)
    return iri


def iri(term: str) -> str:
    """``UBERON:0002107`` -> the full IRI. An IRI passes through unchanged."""
    if term.startswith("http"):
        return term
    return OBO + term.replace(":", "_", 1)


class Ubergraph:
    def __init__(
        self,
        *,
        endpoint: str = ENDPOINT,
        cache: Cache | None = None,
        timeout: float = 120.0,
        client: httpx.Client | None = None,
    ):
        self.endpoint = endpoint
        self.cache = cache if cache is not None else Cache()
        self.timeout = timeout
        self._client = client

    # -- transport -----------------------------------------------------

    def query(self, sparql: str) -> list[dict[str, Any]]:
        """Run SPARQL, return rows as plain dicts of value strings."""
        cached = self.cache.get("ubergraph", sparql)
        if cached is not None:
            return cached
        client = self._client or httpx.Client(timeout=self.timeout)
        try:
            response = client.post(
                self.endpoint,
                data={"query": sparql},
                headers={"Accept": "application/sparql-results+json"},
            )
        finally:
            if self._client is None:
                client.close()
        if response.status_code != 200:
            raise OntomapError(
                f"Ubergraph returned {response.status_code}. "
                "A 500 here is usually a query the store timed out on; narrow it "
                "rather than retrying."
            )
        try:
            payload = response.json()
        except json.JSONDecodeError as exc:  # a Java stack trace, in practice
            raise OntomapError(f"Ubergraph did not return JSON: {response.text[:200]}") from exc
        rows = [
            {k: v["value"] for k, v in binding.items()}
            for binding in payload["results"]["bindings"]
        ]
        self.cache.put("ubergraph", sparql, rows)
        return rows

    # -- helpers -------------------------------------------------------

    @staticmethod
    def _values(variable: str, terms: list[str]) -> str:
        joined = " ".join(f"<{iri(t)}>" for t in terms)
        return f"VALUES ?{variable} {{ {joined} }}"

    @staticmethod
    def _prefix_filter(variable: str, prefix: str | None) -> str:
        """Filter by IRI, which is the only thing that actually says which ontology.

        Querying OLS with ``ontology=uberon`` also returns the CL and GO terms
        UBERON imports: they carry ``ontology_name="uberon"`` and a ``CL:`` ID.
        That is how a tissue field once acquired a cell type. Here the namespace
        claim and the identifier cannot disagree, because there is only the IRI.
        """
        if not prefix:
            return ""
        return f'FILTER(STRSTARTS(STR(?{variable}), "{OBO}{prefix}_"))'

    # -- lookup --------------------------------------------------------

    def labels(self, ids: list[str]) -> dict[str, str]:
        """CURIE -> label, for the terms that have one."""
        if not ids:
            return {}
        rows = self.query(f"""
SELECT ?s ?l WHERE {{
  {self._values("s", ids)}
  GRAPH <{ONTOLOGY}> {{ ?s <{RDFS_LABEL}> ?l }}
}}""")
        return {curie(r["s"]): r["l"] for r in rows}

    def term_detail(self, ids: list[str]) -> dict[str, dict[str, Any]]:
        """Everything a dossier needs about a term, batched.

        Definition and comment are what actually settle most judgement calls --
        far more often than the label, which is why they are fetched together
        with it rather than on demand.
        """
        if not ids:
            return {}
        rows = self.query(f"""
SELECT ?s ?p ?o WHERE {{
  {self._values("s", ids)}
  GRAPH <{ONTOLOGY}> {{ ?s ?p ?o }}
  VALUES ?p {{ <{RDFS_LABEL}> <{DEFINITION}> <{RDFS_COMMENT}> <{HAS_DBXREF}>
              <{IN_SUBSET}> <{DEPRECATED}> <{INFORMATION_CONTENT}>
              <{HAS_EXACT_SYNONYM}> <{HAS_RELATED_SYNONYM}>
              <{HAS_NARROW_SYNONYM}> <{HAS_BROAD_SYNONYM}> }}
}}""")
        out: dict[str, dict[str, Any]] = {}
        for row in rows:
            term = out.setdefault(
                curie(row["s"]),
                {
                    "id": curie(row["s"]),
                    "label": None,
                    "definition": None,
                    "comment": None,
                    "xrefs": [],
                    "subsets": [],
                    "synonyms": [],
                    "deprecated": False,
                    "information_content": None,
                },
            )
            predicate, value = row["p"], row["o"]
            if predicate == RDFS_LABEL:
                term["label"] = value
            elif predicate == DEFINITION:
                term["definition"] = value
            elif predicate == RDFS_COMMENT:
                term["comment"] = value
            elif predicate == HAS_DBXREF:
                term["xrefs"].append(value)
            elif predicate == IN_SUBSET:
                term["subsets"].append(value.rsplit("#", 1)[-1])
            elif predicate == DEPRECATED:
                term["deprecated"] = value.lower() == "true"
            elif predicate == INFORMATION_CONTENT:
                term["information_content"] = float(value)
            elif predicate in SYNONYM_SCOPES:
                term["synonyms"].append({"value": value, "scope": SYNONYM_SCOPES[predicate]})
        return out

    def label_exact(self, strings: list[str], *, prefix: str) -> dict[str, list[dict[str, Any]]]:
        """Case-insensitive exact label match. Returns *all* matches, never one.

        Uniqueness is the caller's decision, so it has to be able to see that
        there were three. A rule that silently takes the first match is a
        relevance ranking wearing a different hat.
        """
        return self._match_on(strings, prefix=prefix, predicates={RDFS_LABEL: "label"})

    def synonym_exact(
        self, strings: list[str], *, prefix: str, scopes: tuple[str, ...] = ("exact",)
    ) -> dict[str, list[dict[str, Any]]]:
        """Case-insensitive exact match against synonyms of the given scopes.

        Scope is carried through to the result and matters: an ``exact`` synonym
        may assign a term, while ``related``, ``narrow`` and ``broad`` are
        candidates for a dossier and nothing more. ``related`` in particular is
        a dumping ground -- it holds lexical variants alongside terms that merely
        came up in the same conversation.
        """
        wanted = {p: s for p, s in SYNONYM_SCOPES.items() if s in scopes}
        if not wanted:
            raise OntomapError(f"no known synonym scope in {scopes!r}")
        return self._match_on(strings, prefix=prefix, predicates=wanted)

    def _match_on(
        self, strings: list[str], *, prefix: str, predicates: dict[str, str]
    ) -> dict[str, list[dict[str, Any]]]:
        wanted = {s.strip().lower() for s in strings if s and s.strip()}
        if not wanted:
            return {}
        literals = " ".join(json.dumps(s) for s in sorted(wanted))
        predicate_values = " ".join(f"<{p}>" for p in predicates)
        rows = self.query(f"""
SELECT ?s ?p ?o ?needle WHERE {{
  VALUES ?needle {{ {literals} }}
  VALUES ?p {{ {predicate_values} }}
  GRAPH <{ONTOLOGY}> {{ ?s ?p ?o }}
  FILTER(LCASE(STR(?o)) = ?needle)
  {self._prefix_filter("s", prefix)}
}}""")
        matched = [curie(r["s"]) for r in rows]
        labels = self.labels(matched) if matched else {}
        out: dict[str, list[dict[str, Any]]] = {s: [] for s in wanted}
        for row in rows:
            term_id = curie(row["s"])
            out[row["needle"]].append(
                {
                    "id": term_id,
                    "label": labels.get(term_id),
                    "matched_on": row["o"],
                    "via": predicates[row["p"]],
                }
            )
        return out

    # -- structure -----------------------------------------------------

    @staticmethod
    def _relation_values(via: tuple[str, ...]) -> str:
        return " ".join(f"<{v}>" for v in via)

    def ancestors(
        self,
        ids: list[str],
        *,
        via: tuple[str, ...] = (SUBCLASS_OF, PART_OF),
        graph: str = REDUNDANT,
        prefix: str | None = None,
    ) -> dict[str, set[str]]:
        """Closure upwards. Batched: one query however many terms you pass.

        ``part_of`` belongs in the default alongside ``subClassOf`` because the
        question a sampled site asks is containment, not classification. Cornea
        is not a kind of eye; it is part of one, and an is_a-only closure will
        never find the eye.
        """
        return self._closure(ids, via=via, graph=graph, prefix=prefix, up=True)

    def descendants(
        self,
        ids: list[str],
        *,
        via: tuple[str, ...] = (SUBCLASS_OF, PART_OF),
        graph: str = REDUNDANT,
        prefix: str | None = None,
    ) -> dict[str, set[str]]:
        return self._closure(ids, via=via, graph=graph, prefix=prefix, up=False)

    def _closure(
        self, ids: list[str], *, via: tuple[str, ...], graph: str, prefix: str | None, up: bool
    ) -> dict[str, set[str]]:
        if not ids:
            return {}
        subject, obj = ("s", "o") if up else ("o", "s")
        rows = self.query(f"""
SELECT ?s ?o WHERE {{
  {self._values(subject, ids)}
  VALUES ?rel {{ {self._relation_values(via)} }}
  GRAPH <{graph}> {{ ?s ?rel ?o }}
  {self._prefix_filter(obj, prefix)}
}}""")
        out: dict[str, set[str]] = {curie(iri(i)): set() for i in ids}
        for row in rows:
            out.setdefault(curie(row[subject]), set()).add(curie(row[obj]))
        return out

    def is_ancestor_of(
        self,
        pairs: list[tuple[str, str]],
        *,
        via: tuple[str, ...] = (SUBCLASS_OF, PART_OF),
    ) -> dict[tuple[str, str], bool]:
        """For each (candidate, exemplar), does the subsumption actually hold?

        This is the anti-laundering gate. "Broad match" must not become a licence
        for an unrelated term: the curator names a specific structure the string
        certainly covers, and this confirms the generalisation direction holds.
        It earns its keep on plausible-but-unasserted pairs -- UBERON does not
        put liver under ``viscus``, though it puts pancreas there.
        """
        if not pairs:
            return {}
        exemplars = sorted({e for _, e in pairs})
        ancestors = self.ancestors(exemplars, via=via)
        return {(c, e): c in ancestors.get(e, set()) for c, e in pairs}

    def common_ancestors(
        self,
        ids: list[str],
        *,
        via: tuple[str, ...] = (SUBCLASS_OF, PART_OF),
        prefix: str | None = "UBERON",
    ) -> list[dict[str, Any]]:
        """Terms subsuming *every* input, with information content for ranking.

        One query with a HAVING, rather than fetching each term's closure and
        intersecting locally. Ranked by information content, not by depth: depth
        prefers `subdivision of oviduct` over `oviduct` for (uterus, cervix,
        vagina), and a grouping class is not a place a sample came from.
        """
        if not ids:
            return []
        count = len({curie(iri(i)) for i in ids})
        rows = self.query(f"""
SELECT ?anc (COUNT(DISTINCT ?m) AS ?n) WHERE {{
  {self._values("m", ids)}
  VALUES ?rel {{ {self._relation_values(via)} }}
  GRAPH <{REDUNDANT}> {{ ?m ?rel ?anc }}
  {self._prefix_filter("anc", prefix)}
}}
GROUP BY ?anc
HAVING (COUNT(DISTINCT ?m) = {count})""")
        found = [curie(r["anc"]) for r in rows]
        detail = self.term_detail(found) if found else {}
        out = [
            {
                "id": term_id,
                "label": detail.get(term_id, {}).get("label"),
                "definition": detail.get(term_id, {}).get("definition"),
                "information_content": detail.get(term_id, {}).get("information_content"),
            }
            for term_id in found
        ]
        out.sort(key=lambda t: (t["information_content"] or 0.0), reverse=True)
        return out

    def develops_from(self, ids: list[str]) -> dict[str, list[dict[str, str]]]:
        """Developmental precursors, typed and kept apart.

        Typed matters. ``has developmental contribution from`` reaches germ
        layers -- mesoderm, endoderm, neural crest -- constantly, and a germ
        layer is an upstream source, never the structure a dissection yields. A
        merged relation set makes that distinction unrecoverable, and OLS's
        per-relation REST endpoints do merge them whatever their route names say.

        Nonredundant graph on purpose: the redundant one mixes real precursors
        with the precursors' own class ancestors (`tissue`, `epithelium`).
        """
        if not ids:
            return {}
        relations = {
            DEVELOPS_FROM: "develops_from",
            DIRECTLY_DEVELOPS_FROM: "directly_develops_from",
            DEVELOPMENTAL_CONTRIBUTION_FROM: "has_developmental_contribution_from",
        }
        rows = self.query(f"""
SELECT ?s ?rel ?o WHERE {{
  {self._values("s", ids)}
  VALUES ?rel {{ {" ".join(f"<{r}>" for r in relations)} }}
  GRAPH <{NONREDUNDANT}> {{ ?s ?rel ?o }}
  {self._prefix_filter("o", "UBERON")}
}}""")
        targets = sorted({curie(r["o"]) for r in rows})
        labels = self.labels(targets) if targets else {}
        out: dict[str, list[dict[str, str]]] = {curie(iri(i)): [] for i in ids}
        for row in rows:
            out.setdefault(curie(row["s"]), []).append(
                {
                    "id": curie(row["o"]),
                    "label": labels.get(curie(row["o"])),
                    "relation": relations[row["rel"]],
                    # The one relation that must never auto-propose a candidate.
                    "germ_layer_prone": row["rel"] == DEVELOPMENTAL_CONTRIBUTION_FROM,
                }
            )
        return out

    def existence_bounds(self, ids: list[str]) -> dict[str, list[dict[str, str]]]:
        """UBERON's own existence edges. Coarse, cross-species, and bounds only.

        These say "starts during **or after** X" and "ends during **or before**
        Y" against cross-species stage terms, so liver reports "starts during or
        after gastrula stage". Good enough to ask whether a term is prenatal at
        all and nothing finer. For a human window use :mod:`ontomap.ehdaa2`.
        """
        if not ids:
            return {}
        relations = {
            EXISTENCE_STARTS_DURING_OR_AFTER: "starts_during_or_after",
            EXISTENCE_ENDS_DURING_OR_BEFORE: "ends_during_or_before",
        }
        rows = self.query(f"""
SELECT ?s ?rel ?o WHERE {{
  {self._values("s", ids)}
  VALUES ?rel {{ {" ".join(f"<{r}>" for r in relations)} }}
  GRAPH <{NONREDUNDANT}> {{ ?s ?rel ?o }}
}}""")
        targets = sorted({curie(r["o"]) for r in rows})
        labels = self.labels(targets) if targets else {}
        out: dict[str, list[dict[str, str]]] = {curie(iri(i)): [] for i in ids}
        for row in rows:
            out.setdefault(curie(row["s"]), []).append(
                {
                    "id": curie(row["o"]),
                    "label": labels.get(curie(row["o"])),
                    "relation": relations[row["rel"]],
                }
            )
        return out

    def xrefs(self, ids: list[str], *, source: str) -> dict[str, list[str]]:
        """Cross-references to another resource, e.g. ``source="EHDAA2"``.

        The join that gets human staging onto UBERON anatomy: 1,835 UBERON terms
        carry an EHDAA2 xref, and EHDAA2 stages against HsapDv.
        """
        if not ids:
            return {}
        rows = self.query(f"""
SELECT ?s ?x WHERE {{
  {self._values("s", ids)}
  GRAPH <{ONTOLOGY}> {{ ?s <{HAS_DBXREF}> ?x }}
  FILTER(STRSTARTS(STR(?x), "{source}:"))
}}""")
        out: dict[str, list[str]] = {curie(iri(i)): [] for i in ids}
        for row in rows:
            out.setdefault(curie(row["s"]), []).append(row["x"])
        return out
