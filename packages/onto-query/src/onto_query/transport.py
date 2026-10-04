"""HTTP transport for OLS4 and Ubergraph.

Kept deliberately small and dependency-free. Two things it exists to enforce:

- SPARQL goes out by POST, never GET. Ubergraph returns HTTP 403 when a GET URL
  grows long, which happens as soon as a VALUES block carries a hundred CURIEs.
- OLS4 latency is erratic (measured 0.96-28s on identical calls), so every
  request gets a generous timeout and a bounded retry.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field

OLS4_BASE = "https://www.ebi.ac.uk/ols4/api"
OLS4_SEARCH = f"{OLS4_BASE}/search"
UBERGRAPH_SPARQL = "https://ubergraph.apps.renci.org/sparql"

USER_AGENT = "onto-query/0.2.0"


class TransportError(RuntimeError):
    """A request failed after retries."""


@dataclass
class Transport:
    """Performs the network calls. Swap for a replaying stub in tests."""

    timeout: float = 90.0
    retries: int = 2
    backoff: float = 2.0
    calls: list[dict] = field(default_factory=list, repr=False)

    def _open(self, req: urllib.request.Request) -> bytes:
        last: Exception | None = None
        for attempt in range(self.retries + 1):
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as r:
                    return r.read()
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                last = exc
                if attempt < self.retries:
                    time.sleep(self.backoff * (attempt + 1))
        raise TransportError(f"{req.full_url}: {last}") from last

    def ols4_search(self, params: dict[str, str]) -> dict:
        url = OLS4_SEARCH + "?" + urllib.parse.urlencode(params)
        req = urllib.request.Request(
            url, headers={"Accept": "application/json", "User-Agent": USER_AGENT}
        )
        self.calls.append({"backend": "ols4", "params": dict(params)})
        return json.loads(self._open(req))

    def ols4_ontology(self, ontology: str) -> dict:
        """Per-ontology OLS4 config: which properties count as label, synonym
        and definition for this ontology. Not uniform -- EFO declares
        efo:alternative_term alongside hasExactSynonym, while most OBO
        ontologies leave it empty and take OLS4's defaults."""
        url = f"{OLS4_BASE}/ontologies/{urllib.parse.quote(ontology)}"
        req = urllib.request.Request(
            url, headers={"Accept": "application/json", "User-Agent": USER_AGENT}
        )
        self.calls.append({"backend": "ols4", "ontology": ontology})
        return json.loads(self._open(req))

    def ols4_v2_class(self, ontology: str, iri: str) -> dict:
        """v2 entity record. Carries `linkedEntities`, which is where OLS4
        resolves every referenced CURIE -- xrefs included -- to a label, a
        defining ontology, a resolvable URL and the registry that supplied it.
        The v1 API has no equivalent."""
        # v2 wants the IRI double-encoded in the path.
        enc = urllib.parse.quote(urllib.parse.quote(iri, safe=""), safe="")
        url = f"{OLS4_BASE}/v2/ontologies/{urllib.parse.quote(ontology)}/classes/{enc}"
        req = urllib.request.Request(
            url, headers={"Accept": "application/json", "User-Agent": USER_AGENT}
        )
        self.calls.append({"backend": "ols4-v2", "ontology": ontology, "iri": iri})
        return json.loads(self._open(req))

    def ols4_graph(self, ontology: str, iri: str) -> dict:
        """v1 term graph: the one-hop neighbourhood as nodes and labelled edges.

        Works for any ontology OLS4 holds, including the ~240 that Ubergraph
        does not, so it is the route to relations for those. Note the IRI is
        double-encoded in the path; single-encoding returns HTTP 400.
        """
        enc = urllib.parse.quote(urllib.parse.quote(iri, safe=""), safe="")
        url = f"{OLS4_BASE}/ontologies/{urllib.parse.quote(ontology)}/terms/{enc}/graph"
        req = urllib.request.Request(
            url, headers={"Accept": "application/json", "User-Agent": USER_AGENT}
        )
        self.calls.append({"backend": "ols4-graph", "ontology": ontology, "iri": iri})
        return json.loads(self._open(req))

    def ols4_hierarchy(
        self, ontology: str, iri: str, relation: str, size: int = 1000, page: int = 0
    ) -> dict:
        """One page of a v1 hierarchy sub-resource.

        `relation` is one of ancestors, descendants, parents, children, or their
        hierarchical* forms. `size` is capped at 1000 by the server; asking for
        more is silently clamped. The IRI is double-encoded, as everywhere under
        /terms/.
        """
        enc = urllib.parse.quote(urllib.parse.quote(iri, safe=""), safe="")
        qs = urllib.parse.urlencode({"size": size, "page": page})
        url = f"{OLS4_BASE}/ontologies/{urllib.parse.quote(ontology)}/terms/{enc}/{relation}?{qs}"
        req = urllib.request.Request(
            url, headers={"Accept": "application/json", "User-Agent": USER_AGENT}
        )
        self.calls.append(
            {
                "backend": "ols4-hierarchy",
                "ontology": ontology,
                "iri": iri,
                "relation": relation,
                "page": page,
            }
        )
        return json.loads(self._open(req))

    def sparql(self, query: str) -> dict:
        body = urllib.parse.urlencode({"query": query}).encode()
        req = urllib.request.Request(
            UBERGRAPH_SPARQL,
            data=body,  # POST: a long VALUES block 403s over GET
            headers={
                "Accept": "application/sparql-results+json",
                "Content-Type": "application/x-www-form-urlencoded",
                "User-Agent": USER_AGENT,
            },
        )
        self.calls.append({"backend": "ubergraph", "query": query})
        return json.loads(self._open(req))


def sparql_rows(result: dict) -> list[dict[str, str]]:
    """Flatten a SPARQL JSON result to a list of {var: value}."""
    return [
        {k: v["value"] for k, v in binding.items()}
        for binding in result.get("results", {}).get("bindings", [])
    ]
