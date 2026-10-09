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


# Namespaces that appear as predicates in Ubergraph's graphs. Without these,
# rdfs:subClassOf comes back from `term` as a bare IRI, which no other command
# will accept.
WELL_KNOWN = {
    "http://www.w3.org/2000/01/rdf-schema#": "rdfs",
    "http://www.w3.org/2002/07/owl#": "owl",
    "http://www.w3.org/2004/02/skos/core#": "skos",
    "http://www.geneontology.org/formats/oboInOwl#": "oio",
    "http://www.w3.org/1999/02/22-rdf-syntax-ns#": "rdf",
}


def to_curie(iri: str) -> str:
    """Inverse of to_iri, falling back to the IRI when there is no safe CURIE.

    Falling back matters more than it looks. Uberon carries predicates in its
    own namespace -- ``.../obo/uberon/core#extends_fibers_into`` -- whose tail
    contains an underscore but is not an OBO-style ``PREFIX_LOCALID``. Splitting
    on the first underscore regardless produced ``core#extends:fibers_into``,
    which is not a CURIE, cannot be passed back to ``relations -p``, and looks
    enough like one to be believed. Anything that does not match the OBO shape
    is returned as an IRI, which every command here accepts.
    """
    for ns, prefix in WELL_KNOWN.items():
        if iri.startswith(ns):
            return f"{prefix}:{iri[len(ns):]}"
    if iri.startswith(OBO):
        tail = iri[len(OBO):]
        prefix, sep, local = tail.partition("_")
        if sep and prefix.isalnum() and local and "/" not in tail and "#" not in tail:
            return f"{prefix}:{local}"
    return iri


def defined_by_iri(ontology: str) -> str:
    """Ontology short name -> the IRI used in rdfs:isDefinedBy triples.

    Confirmed against Ubergraph for uberon and go; the pattern is uniform for
    OBO ontologies.
    """
    return f"{OBO}{ontology.lower()}.owl"
