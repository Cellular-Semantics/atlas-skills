"""Record and replay backend responses so the unit suite never hits the network.

CI must not depend on OLS4 (latency measured between 0.96 and 28s on identical
calls) or on either source's content, which changes under us. Re-record
deliberately with ``python tests/record_fixtures.py`` and review the diff.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures"


def key_for(kind: str, payload: str) -> str:
    digest = hashlib.sha256(payload.encode()).hexdigest()[:16]
    return f"{kind}-{digest}"


def _ols_payload(params: dict[str, str]) -> str:
    return json.dumps(params, sort_keys=True)


@dataclass
class ReplayTransport:
    """Transport stand-in that reads recorded responses."""

    strict: bool = True
    calls: list[dict] = field(default_factory=list)

    def _load(self, kind: str, payload: str) -> dict:
        path = FIXTURES / f"{key_for(kind, payload)}.json"
        if not path.exists():
            if self.strict:
                raise AssertionError(
                    f"no fixture for {kind} request; re-record with "
                    f"tests/record_fixtures.py\npayload: {payload[:400]}"
                )
            return {}
        return json.loads(path.read_text())["response"]

    def ols4_search(self, params: dict[str, str]) -> dict:
        self.calls.append({"backend": "ols4", "params": dict(params)})
        return self._load("ols4", _ols_payload(params))

    def ols4_ontology(self, ontology: str) -> dict:
        self.calls.append({"backend": "ols4", "ontology": ontology})
        return self._load("ols4-ontology", ontology)

    def ols4_v2_class(self, ontology: str, iri: str) -> dict:
        self.calls.append({"backend": "ols4-v2", "ontology": ontology, "iri": iri})
        return self._load("ols4-v2", f"{ontology}|{iri}")

    def ols4_graph(self, ontology: str, iri: str) -> dict:
        self.calls.append({"backend": "ols4-graph", "ontology": ontology, "iri": iri})
        return self._load("ols4-graph", f"{ontology}|{iri}")

    def ols4_hierarchy(
        self, ontology: str, iri: str, relation: str, size: int = 1000, page: int = 0
    ) -> dict:
        self.calls.append(
            {
                "backend": "ols4-hierarchy",
                "ontology": ontology,
                "iri": iri,
                "relation": relation,
                "page": page,
            }
        )
        return self._load("ols4-hierarchy", f"{ontology}|{iri}|{relation}|{size}|{page}")

    def sparql(self, query: str) -> dict:
        self.calls.append({"backend": "ubergraph", "query": query})
        return self._load("sparql", query)


@dataclass
class RecordingTransport:
    """Wraps a real Transport and writes every response to the fixture dir."""

    inner: object
    written: list[str] = field(default_factory=list)

    def _write(self, kind: str, payload: str, response: dict) -> None:
        FIXTURES.mkdir(parents=True, exist_ok=True)
        name = f"{key_for(kind, payload)}.json"
        (FIXTURES / name).write_text(
            json.dumps({"kind": kind, "payload": payload, "response": response}, indent=1)
        )
        self.written.append(name)

    def ols4_search(self, params: dict[str, str]) -> dict:
        resp = self.inner.ols4_search(params)
        self._write("ols4", _ols_payload(params), resp)
        return resp

    def ols4_ontology(self, ontology: str) -> dict:
        resp = self.inner.ols4_ontology(ontology)
        self._write("ols4-ontology", ontology, resp)
        return resp

    def ols4_v2_class(self, ontology: str, iri: str) -> dict:
        resp = self.inner.ols4_v2_class(ontology, iri)
        self._write("ols4-v2", f"{ontology}|{iri}", resp)
        return resp

    def ols4_graph(self, ontology: str, iri: str) -> dict:
        resp = self.inner.ols4_graph(ontology, iri)
        self._write("ols4-graph", f"{ontology}|{iri}", resp)
        return resp

    def ols4_hierarchy(
        self, ontology: str, iri: str, relation: str, size: int = 1000, page: int = 0
    ) -> dict:
        resp = self.inner.ols4_hierarchy(ontology, iri, relation, size, page)
        self._write("ols4-hierarchy", f"{ontology}|{iri}|{relation}|{size}|{page}", resp)
        return resp

    def sparql(self, query: str) -> dict:
        resp = self.inner.sparql(query)
        self._write("sparql", query, resp)
        return resp
