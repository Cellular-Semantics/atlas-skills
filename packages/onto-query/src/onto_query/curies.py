"""CURIE / IRI conversion for OBO-style identifiers."""

from __future__ import annotations

OBO = "http://purl.obolibrary.org/obo/"


def to_iri(curie: str) -> str:
    """UBERON:0002097 -> http://purl.obolibrary.org/obo/UBERON_0002097"""
    if curie.startswith("http://") or curie.startswith("https://"):
        return curie
    prefix, _, local = curie.partition(":")
    if not local:
        raise ValueError(f"not a CURIE: {curie!r}")
    return f"{OBO}{prefix}_{local}"


def to_curie(iri: str) -> str:
    """Inverse of to_iri, falling back to the IRI when it is not an OBO term."""
    tail = iri.rsplit("/", 1)[-1]
    if "_" in tail and iri.startswith(OBO):
        prefix, _, local = tail.partition("_")
        return f"{prefix}:{local}"
    return iri


def defined_by_iri(ontology: str) -> str:
    """Ontology short name -> the IRI used in rdfs:isDefinedBy triples.

    Confirmed against Ubergraph for uberon and go; the pattern is uniform for
    OBO ontologies.
    """
    return f"{OBO}{ontology.lower()}.owl"
