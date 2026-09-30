"""Live checks against Ubergraph and OLS. Deselected by default; run with -m live.

These exist because the structural assumptions this package rests on are claims
about someone else's data, and a snapshot rebuild can quietly falsify one. They
are separate from the offline suite so that a service outage cannot turn CI red
for a reason that has nothing to do with the code.
"""

import pytest

from ontomap import index
from ontomap.ladder import resolve
from ontomap.ubergraph import PART_OF, SUBCLASS_OF, Ubergraph

pytestmark = pytest.mark.live


@pytest.fixture(scope="module")
def graph():
    return Ubergraph()


@pytest.fixture(scope="module")
def uberon(graph):
    return index.build(graph, prefix="UBERON")


def test_the_axioms_live_in_the_graph_we_think_they_do(graph):
    """Querying the wrong graph returns zero rows, which reads as 'not asserted'.

    Both of these are empty in the `ontology` graph and populated in
    `nonredundant`. The mistake has been made twice; this is the tripwire.
    """
    rows = graph.query("""
SELECT (COUNT(*) AS ?n) WHERE {
  GRAPH <http://reasoner.renci.org/nonredundant> {
    ?s <http://purl.obolibrary.org/obo/RO_0002496> ?o
  }
  FILTER(STRSTARTS(STR(?s), "http://purl.obolibrary.org/obo/UBERON_"))
}""")
    assert int(rows[0]["n"]) > 1000


def test_skin_does_not_resolve_to_a_grouping_class(uberon):
    assert resolve("skin", uberon).term_id is None


def test_the_catalogue_of_disasters_still_refuses(uberon):
    for text in ("upper reproductive tract", "mid vertebrae", "internal organs", "embryo head"):
        assert resolve(text, uberon).term_id is None, text


def test_liver_is_not_asserted_under_viscus(graph):
    holds = graph.is_ancestor_of([("UBERON:0002323", "UBERON:0002107")])
    assert holds[("UBERON:0002323", "UBERON:0002107")] is False


def test_part_of_only_drops_the_grouping_class_that_ties_on_specificity(graph):
    combined = graph.common_ancestors(
        ["UBERON:0000995", "UBERON:0000002", "UBERON:0000996"], via=(SUBCLASS_OF, PART_OF)
    )
    containment = graph.common_ancestors(
        ["UBERON:0000995", "UBERON:0000002", "UBERON:0000996"], via=(PART_OF,)
    )
    labels_combined = {a["label"] for a in combined}
    labels_containment = {a["label"] for a in containment}
    assert "subdivision of oviduct" in labels_combined
    assert "subdivision of oviduct" not in labels_containment
    assert "oviduct" in labels_containment
