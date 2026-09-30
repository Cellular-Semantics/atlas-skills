"""A local label and synonym table, fetched once per ontology and reused.

The exact rungs of the ladder can be answered by Ubergraph directly, batched and
cached. The *normalised* and *token-set* rungs cannot: they compare a candidate
against every label and synonym in the ontology, so the ontology has to be
local. UBERON is ~16k terms and MONDO ~36k, which is nothing to hold in memory
and one query to fetch.

Everything here is derived from that one fetch, so the whole lexical layer is
deterministic and offline after first use -- no relevance ranking anywhere in
the path that can assign a term.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .lexical import normalise, token_set
from .ubergraph import (
    HAS_BROAD_SYNONYM,
    HAS_EXACT_SYNONYM,
    HAS_NARROW_SYNONYM,
    HAS_RELATED_SYNONYM,
    ONTOLOGY,
    RDFS_LABEL,
    SYNONYM_SCOPES,
    Ubergraph,
    curie,
)


@dataclass
class Entry:
    """One string an ontology offers for a term, and how strongly it offers it."""

    term_id: str
    text: str
    via: str  # "label", or a synonym scope: exact | related | narrow | broad


@dataclass
class LexicalIndex:
    prefix: str
    labels: dict[str, str] = field(default_factory=dict)
    by_normalised: dict[str, list[Entry]] = field(default_factory=dict)
    by_token_set: dict[frozenset[str], list[Entry]] = field(default_factory=dict)

    def normalised(self, text: str) -> list[Entry]:
        return list(self.by_normalised.get(normalise(text), []))

    def tokens(self, text: str) -> list[Entry]:
        return list(self.by_token_set.get(token_set(text), []))

    def __len__(self) -> int:
        return len(self.labels)


def build(ubergraph: Ubergraph, *, prefix: str) -> LexicalIndex:
    """Fetch every label and synonym for an ontology and index it two ways."""
    rows = ubergraph.query(f"""
SELECT ?s ?p ?o WHERE {{
  GRAPH <{ONTOLOGY}> {{ ?s ?p ?o }}
  VALUES ?p {{ <{RDFS_LABEL}> <{HAS_EXACT_SYNONYM}> <{HAS_RELATED_SYNONYM}>
              <{HAS_NARROW_SYNONYM}> <{HAS_BROAD_SYNONYM}> }}
  FILTER(STRSTARTS(STR(?s), "http://purl.obolibrary.org/obo/{prefix}_"))
}}""")
    index = LexicalIndex(prefix=prefix)
    entries: list[Entry] = []
    for row in rows:
        term_id = curie(row["s"])
        via = "label" if row["p"] == RDFS_LABEL else SYNONYM_SCOPES[row["p"]]
        if via == "label":
            index.labels[term_id] = row["o"]
        entries.append(Entry(term_id=term_id, text=row["o"], via=via))
    for entry in entries:
        key = normalise(entry.text)
        if key:
            index.by_normalised.setdefault(key, []).append(entry)
        tokens = token_set(entry.text)
        if tokens:
            index.by_token_set.setdefault(tokens, []).append(entry)
    return index


def as_candidates(entries: list[Entry], index: LexicalIndex) -> list[dict[str, Any]]:
    """Entries in the shape the rest of the pipeline and the dossiers expect."""
    seen: dict[tuple[str, str], dict[str, Any]] = {}
    for entry in entries:
        key = (entry.term_id, entry.via)
        if key not in seen:
            seen[key] = {
                "id": entry.term_id,
                "label": index.labels.get(entry.term_id),
                "matched_on": entry.text,
                "via": entry.via,
            }
    return list(seen.values())
