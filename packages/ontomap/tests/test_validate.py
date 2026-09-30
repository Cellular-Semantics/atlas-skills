"""The gates, against a fake OLS. A gate that cannot fail is not a gate."""

from conftest import FakeUbergraph
from ontomap import validate

LIVE = {
    "UBERON:0002107": {"id": "UBERON:0002107", "label": "liver", "obsolete": False},
    "UBERON:0002323": {"id": "UBERON:0002323", "label": "viscus", "obsolete": False},
    "CL:4030001": {"id": "CL:4030001", "label": "stromal cell of thymus", "obsolete": False},
    "UBERON:0000933": {"id": "UBERON:0000933", "label": "gone", "obsolete": True},
}


class FakeOls:
    def lookup(self, term_id):
        return LIVE.get(term_id)


def gates(results, name):
    return [r for r in results if r.gate == name]


def test_label_matches_catches_an_id_that_is_not_what_was_recorded():
    results = validate.check_terms(
        [{"id": "UBERON:0002107", "name": "pancreas"}], FakeOls(), field="tissue"
    )
    assert gates(results, "LABEL_MATCHES")[0].passed is False


def test_id_resolves_catches_an_invented_id():
    results = validate.check_terms(
        [{"id": "UBERON:9999999", "name": "invented"}], FakeOls(), field="tissue"
    )
    assert gates(results, "ID_RESOLVES")[0].passed is False


def test_prefix_expected_catches_a_cell_type_in_a_tissue_field():
    # Querying an ontology by name also returns the terms it imports: they
    # carry the importing ontology's name and their own id.
    results = validate.check_terms(
        [{"id": "CL:4030001", "name": "stromal cell of thymus"}], FakeOls(), field="tissue"
    )
    assert gates(results, "PREFIX_EXPECTED")[0].passed is False


def test_obsolete_terms_fail():
    results = validate.check_terms(
        [{"id": "UBERON:0000933", "name": "gone"}], FakeOls(), field="tissue"
    )
    assert gates(results, "NOT_OBSOLETE")[0].passed is False


def test_disease_field_accepts_the_normal_convention():
    results = validate.check_terms(
        [{"id": "PATO:0000461", "name": "normal"}], FakeOls(), field="disease"
    )
    assert gates(results, "PREFIX_EXPECTED")[0].passed is True


def test_broad_is_ancestor_rejects_an_unasserted_subsumption():
    """The term may be right and the exemplar wrong, and only a query can tell.

    `viscus` was proposed for "internal organs" with liver as the exemplar.
    UBERON does not assert liver under viscus, though it does assert pancreas.
    """
    graph = FakeUbergraph(ancestors={"UBERON:0002107": {"UBERON:0000062"}})
    results = validate.check_broad_matches(
        [{"term_id": "UBERON:0002323", "exemplar_specific_term_id": "UBERON:0002107"}], graph
    )
    assert gates(results, "BROAD_IS_ANCESTOR")[0].passed is False


def test_broad_is_ancestor_passes_a_real_one():
    graph = FakeUbergraph(ancestors={"UBERON:0002107": {"UBERON:0002323"}})
    results = validate.check_broad_matches(
        [{"term_id": "UBERON:0002323", "exemplar_specific_term_id": "UBERON:0002107"}], graph
    )
    assert gates(results, "BROAD_IS_ANCESTOR")[0].passed is True


def test_not_self_rejects_a_broad_match_that_is_the_exemplar():
    graph = FakeUbergraph(ancestors={"UBERON:0002107": {"UBERON:0002107"}})
    results = validate.check_broad_matches(
        [{"term_id": "UBERON:0002107", "exemplar_specific_term_id": "UBERON:0002107"}], graph
    )
    assert gates(results, "NOT_SELF")[0].passed is False


def test_a_missing_specific_term_is_skipped_not_silently_passed():
    graph = FakeUbergraph()
    results = validate.check_broad_matches(
        [{"term_id": "UBERON:0002323", "specific_term_missing": True}], graph
    )
    assert "new-term request" in gates(results, "BROAD_IS_ANCESTOR")[0].detail
