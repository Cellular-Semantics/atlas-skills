"""OLS, used for two jobs that must stay apart: finding candidates, and validating.

**Search** is the only lexical retrieval here that tolerates a misspelling or a
partial phrase, and it is the only thing OLS is asked to do in the matching
path. Nothing it returns is ever written into a term id. The rule is absolute
because the alternative has a track record: ranked first for `upper reproductive
tract` was `lateral nasal gland`, a rodent gland, and for `mid vertebrae` a neck
muscle whose *definition* mentions vertebrae.

**Validation** is the second job and it is deliberately answered by a different
service from the one that assigned the term. Ubergraph is a periodic snapshot
and lags OBO releases; if the store that produced an answer also checks it,
`LABEL_MATCHES` and `NOT_OBSOLETE` check nothing at all. Two sources disagreeing
is itself a finding -- usually a stale snapshot, occasionally a real mistake.
"""

from __future__ import annotations

from typing import Any

import httpx

from .cache import Cache
from .errors import OntomapError

BASE = "https://www.ebi.ac.uk/ols4/api"


class Ols:
    def __init__(
        self,
        *,
        base: str = BASE,
        cache: Cache | None = None,
        timeout: float = 60.0,
        client: httpx.Client | None = None,
    ):
        self.base = base
        self.cache = cache if cache is not None else Cache()
        self.timeout = timeout
        self._client = client

    def _get(self, path: str, params: dict[str, Any], *, allow_missing: bool = False) -> dict[str, Any]:
        key = f"{path}?{sorted(params.items())}"
        cached = self.cache.get("ols", key)
        if cached is not None:
            return cached
        client = self._client or httpx.Client(timeout=self.timeout)
        try:
            response = client.get(f"{self.base}{path}", params=params)
        finally:
            if self._client is None:
                client.close()
        if response.status_code == 404 and allow_missing:
            # An id that does not exist is the answer, not a transport failure.
            # It is also the signature of an invented id, which is the single
            # thing ID_RESOLVES exists to catch, so it must not raise.
            payload: dict[str, Any] = {}
            self.cache.put("ols", key, payload)
            return payload
        if response.status_code != 200:
            raise OntomapError(f"OLS {path} returned {response.status_code}")
        payload = response.json()
        self.cache.put("ols", key, payload)
        return payload

    # -- candidates ----------------------------------------------------

    def search(self, text: str, *, ontology: str, rows: int = 10) -> list[dict[str, Any]]:
        """Lexical candidates. Never an assignment, whatever the ranking says.

        The ``obo_id`` prefix is checked here rather than trusted from the
        ``ontology`` parameter. Querying ``ontology=uberon`` also returns the CL
        and GO terms UBERON imports: they come back labelled as UBERON's and
        carry a ``CL:`` id, which is how a cell type once reached a tissue field.
        """
        payload = self._get(
            "/search",
            {"q": text, "ontology": ontology.lower(), "rows": rows, "type": "class"},
        )
        prefix = f"{ontology.upper()}:"
        out = []
        for doc in payload.get("response", {}).get("docs", []):
            obo_id = doc.get("obo_id") or ""
            if not obo_id.startswith(prefix):
                continue  # imported from another ontology; not this namespace's term
            out.append(
                {
                    "id": obo_id,
                    "label": doc.get("label"),
                    "definition": (doc.get("description") or [None])[0],
                    "source": "ols_search",
                    "rank": len(out) + 1,
                }
            )
        return out

    # -- validation ----------------------------------------------------

    def lookup(self, term_id: str) -> dict[str, Any] | None:
        """Current label and obsoletion for an id, straight from the live release."""
        ontology = term_id.split(":", 1)[0].lower()
        iri = f"http://purl.obolibrary.org/obo/{term_id.replace(':', '_', 1)}"
        payload = self._get(f"/ontologies/{ontology}/terms", {"iri": iri}, allow_missing=True)
        terms = payload.get("_embedded", {}).get("terms", [])
        if not terms:
            return None
        term = terms[0]
        return {
            "id": term.get("obo_id") or term_id,
            "label": term.get("label"),
            "obsolete": bool(term.get("is_obsolete")),
            "definition": (term.get("description") or [None])[0],
        }
