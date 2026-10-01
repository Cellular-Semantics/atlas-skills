"""Offline doubles. No test in this suite touches the network.

The vendored HsapDv and EHDAA2 tables are real data shipped in the package, so
stage and staging tests run against the genuine ontology content without a
service. Only the UBERON structural queries need a double, and it is a plain
lookup table rather than a mock: an assertion about what was called tells you
nothing about whether the answer was right.
"""

from __future__ import annotations

from ontomap.index import Entry, LexicalIndex
from ontomap.lexical import normalise, token_set


class FakeUbergraph:
    """Answers from fixed tables. Unknown terms answer empty, as the real one does."""

    def __init__(
        self,
        *,
        ancestors: dict[str, set[str]] | None = None,
        descendants: dict[str, set[str]] | None = None,
        labels: dict[str, str] | None = None,
        common: list[dict] | None = None,
        develops_from: dict[str, list[dict]] | None = None,
        xrefs: dict[str, list[str]] | None = None,
    ):
        self._ancestors = ancestors or {}
        self._descendants = descendants or {}
        self._labels = labels or {}
        self._common = common or []
        self._develops_from = develops_from or {}
        self._xrefs = xrefs or {}

    def ancestors(self, ids, *, via=None, graph=None, prefix=None):
        return {i: set(self._ancestors.get(i, set())) for i in ids}

    def descendants(self, ids, *, via=None, graph=None, prefix=None):
        return {i: set(self._descendants.get(i, set())) for i in ids}

    def labels(self, ids):
        return {i: self._labels[i] for i in ids if i in self._labels}

    def common_ancestors(self, ids, *, via=None, prefix=None):
        return list(self._common)

    def develops_from(self, ids):
        return {i: list(self._develops_from.get(i, [])) for i in ids}

    def xrefs(self, ids, *, source):
        return {i: list(self._xrefs.get(i, [])) for i in ids}

    def term_detail(self, ids):
        return {i: {"id": i, "label": self._labels.get(i)} for i in ids}

    def is_ancestor_of(self, pairs, *, via=None):
        return {(c, e): c in self._ancestors.get(e, set()) for c, e in pairs}

    def query(self, sparql):  # reverse_index in ehdaa2
        return []


def make_index(prefix: str, entries: list[tuple[str, str, str]]) -> LexicalIndex:
    """Build a LexicalIndex from (term_id, text, via) triples."""
    index = LexicalIndex(prefix=prefix)
    parsed = [Entry(term_id=t, text=x, via=v) for t, x, v in entries]
    for entry in parsed:
        if entry.via == "label":
            index.labels[entry.term_id] = entry.text
    for entry in parsed:
        key = normalise(entry.text)
        if key:
            index.by_normalised.setdefault(key, []).append(entry)
        tokens = token_set(entry.text)
        if tokens:
            index.by_token_set.setdefault(tokens, []).append(entry)
    return index
