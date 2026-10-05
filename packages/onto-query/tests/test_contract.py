"""Contract tests over replayed fixtures. No network.

These pin the things a skill depends on: the JSON shape, the guards, and the
promise that nothing here scores or selects.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

from cassette import ReplayTransport

from onto_query import curies
from onto_query.cli import main as cli_main
from onto_query.ols import lexical
from onto_query.ubergraph import (
    MAX_SEEDS,
    SeedLimitExceeded,
    Ubergraph,
)


@pytest.fixture
def t() -> ReplayTransport:
    return ReplayTransport()


# ---- curies -------------------------------------------------------------


@pytest.mark.parametrize(
    ("curie", "iri"),
    [
        ("UBERON:0002097", "http://purl.obolibrary.org/obo/UBERON_0002097"),
        ("GO:0006096", "http://purl.obolibrary.org/obo/GO_0006096"),
    ],
)
def test_curie_roundtrip(curie, iri):
    assert curies.to_iri(curie) == iri
    assert curies.to_curie(iri) == curie


def test_non_obo_iri_passes_through():
    iri = "https://w3id.org/orcidio/orcidio.owl"
    assert curies.to_curie(iri) == iri


def test_defined_by_iri():
    assert curies.defined_by_iri("uberon") == "http://purl.obolibrary.org/obo/uberon.owl"
    assert curies.defined_by_iri("GO") == "http://purl.obolibrary.org/obo/go.owl"


# ---- lexical probes -----------------------------------------------------


def test_exact_probe_sends_the_two_parameters_that_matter(t):
    """exact=true is close to meaningless without queryFields: on its own it
    still searches definitions and degenerates to token matching."""
    lexical(t, "skin", "uberon", probes=("exact",))
    # calls[0] is now the ontology-config lookup; find the search itself
    params = next(c["params"] for c in t.calls if "params" in c)
    assert params["exact"] == "true"
    assert params["queryFields"] == "label,synonym"
    assert params["local"] == "true"  # without this, imported GO/CL/PR terms leak in
    assert params["obsoletes"] == "false"


def test_skin_exact_returns_the_four_terms(t):
    res = lexical(t, "skin", "uberon", probes=("exact",))
    assert {h["curie"] for h in res["hits"]} == {
        "UBERON:0000014",  # zone of skin
        "UBERON:0002097",  # skin of body
        "UBERON:0001003",  # skin epidermis
        "UBERON:0002199",  # integument
    }


def test_synonym_scope_is_recovered(t):
    """OLS4's `synonym` field is the union of all scopes and the scoped fields
    are not queryable, so scope can only be recovered client-side."""
    res = lexical(t, "skin", "uberon", probes=("exact",))
    by_curie = {h["curie"]: h for h in res["hits"]}
    assert "skin" in by_curie["UBERON:0000014"]["synonyms"]["exact"]
    assert "skin" in by_curie["UBERON:0002097"]["synonyms"]["related"]
    assert "skin" in by_curie["UBERON:0001003"]["synonyms"]["broad"]


def test_no_score_is_returned(t):
    """OLS4 exposes no relevance score -- not in the document, not via fl=score
    or fieldList=score -- so none is invented. Rank is a separate thing: it is
    the observed position in a probe's results, and it is reported."""
    res = lexical(t, "skin", "uberon", probes=("exact",))
    blob = json.dumps(res).lower()
    for forbidden in ("score", "relevance", "confidence"):
        assert forbidden not in blob


def test_rank_is_reported_per_probe(t):
    res = lexical(t, "skin", "uberon", probes=("exact", "stemmed"))
    by_curie = {h["curie"]: h for h in res["hits"]}
    # Measured against the live service: these are Solr's positions.
    assert by_curie["UBERON:0000014"]["found_by"]["stemmed"]["rank"] == 22
    assert by_curie["UBERON:0002097"]["found_by"]["stemmed"]["rank"] == 46


def test_matched_fields_only_for_the_exact_probe(t):
    """Exact is whole-string, so the matched field is a reliable comparison.
    Stemming makes the same reconstruction wrong more often than right."""
    res = lexical(t, "skin", "uberon", probes=("exact", "stemmed"))
    by_curie = {h["curie"]: h for h in res["hits"]}
    assert by_curie["UBERON:0000014"]["found_by"]["exact"]["matched_fields"] == ["exact_synonym"]
    assert by_curie["UBERON:0002097"]["found_by"]["exact"]["matched_fields"] == ["related_synonym"]
    assert by_curie["UBERON:0001003"]["found_by"]["exact"]["matched_fields"] == ["broad_synonym"]
    assert "matched_fields" not in by_curie["UBERON:0000014"]["found_by"]["stemmed"]


def test_probe_metadata_records_what_was_searched(t):
    res = lexical(t, "skin", "uberon", probes=("exact", "stemmed"))
    assert res["probes"]["exact"] == {
        "query_fields": "label,synonym",
        "exact": True,
        "num_found": 4,
        "returned": 4,
        "truncated": False,
    }
    assert res["probes"]["stemmed"]["exact"] is False


def test_truncation_is_visible_not_silent(t):
    """num_found is the backend's true total, so a capped result says so."""
    res = lexical(t, "skin", "uberon", probes=("stemmed",), rows=10)
    info = res["probes"]["stemmed"]
    assert info["returned"] == 10
    assert info["num_found"] == 121
    assert info["truncated"] is True


def test_search_config_reports_per_ontology_synonym_properties(t):
    from onto_query.ols import search_config

    uberon = search_config(t, "uberon")
    assert uberon["uses_ols4_defaults"] is True
    assert uberon["synonym_properties"] == []

    efo = search_config(t, "efo")
    assert efo["uses_ols4_defaults"] is False
    assert "http://www.ebi.ac.uk/efo/alternative_term" in efo["synonym_properties"]


def test_multi_token_query_returning_nothing_is_a_real_result(t):
    res = lexical(t, "full reproductive tract", "uberon", probes=("exact",))
    assert res["total"] == 0
    assert res["probes"]["exact"]["num_found"] == 0


def test_unknown_probe_rejected(t):
    with pytest.raises(ValueError, match="unknown probe"):
        lexical(t, "skin", "uberon", probes=("fuzzy",))


# ---- common ancestors ---------------------------------------------------


def _full_coverage(res):
    return [s for s in res["subsumers"] if not s["missing_seeds"] and not s["is_seed"]]


def test_part_of_is_required_for_grouping_terms(t):
    """Cornea and conjunctiva are *parts of* the ocular surface region, not
    subclasses of it. Over subClassOf alone the answer silently disappears."""
    ug = Ubergraph(t)
    seeds = ["UBERON:0000964", "UBERON:0001811"]

    with_part_of = _full_coverage(ug.common_ancestors(seeds, "uberon"))
    assert with_part_of[0]["curie"] == "UBERON:0010409"

    sub_only = _full_coverage(ug.common_ancestors(seeds, "uberon", predicates=("subClassOf",)))
    assert "UBERON:0010409" not in {s["curie"] for s in sub_only}


def test_seeds_are_flagged_not_dropped(t):
    """The redundant graph is reflexive, so each seed subsumes itself."""
    ug = Ubergraph(t)
    res = ug.common_ancestors(["UBERON:0000964", "UBERON:0001811"], "uberon")
    seeds_in_output = [s for s in res["subsumers"] if s["is_seed"]]
    assert {s["curie"] for s in seeds_in_output} == {"UBERON:0000964", "UBERON:0001811"}


def test_missing_seeds_are_named(t):
    """A hard coverage filter would hide the information needed to spot a bad
    partition, so every subsumer says which seeds it fails to cover."""
    ug = Ubergraph(t)
    res = ug.common_ancestors(["UBERON:0000964", "UBERON:0001811"], "uberon")
    partial = [s for s in res["subsumers"] if s["covers"] < s["of_seeds"]]
    assert partial, "expected some subsumers not to cover every seed"
    for s in partial:
        assert len(s["missing_seeds"]) == s["of_seeds"] - s["covers"]


def test_ic_is_present_and_rounded(t):
    ug = Ubergraph(t)
    res = ug.common_ancestors(["UBERON:0000964", "UBERON:0001811"], "uberon")
    ics = [s["ic"] for s in res["subsumers"] if s["ic"] is not None]
    assert ics and all(round(v, 2) == v for v in ics)


def test_go_band_survives(t):
    """Glycolysis + TCA gives a band of four within 4 IC, then a 39-point cliff.
    The band is the output; collapsing it to a winner would be a decision."""
    ug = Ubergraph(t)
    full = _full_coverage(ug.common_ancestors(["GO:0006096", "GO:0006099"], "go"))
    band = [s for s in full if s["ic"] >= full[0]["ic"] - 4]
    assert len(band) == 4
    assert [s["curie"] for s in band[:2]] == ["GO:0009060", "GO:0045333"]
    assert full[len(band)]["ic"] < full[0]["ic"] - 30  # the cliff


def test_seeds_and_target_ontology_are_independent(t):
    ug = Ubergraph(t)
    full = _full_coverage(ug.common_ancestors(["CL:0000604", "CL:0000573", "CL:0000636"], "uberon"))
    assert full[0]["curie"] == "UBERON:0000966"  # retina


def test_labels_are_a_list(t):
    """GO:0008150 and GO:0110165 each carry two rdfs:label values."""
    ug = Ubergraph(t)
    res = ug.common_ancestors(["GO:0006096", "GO:0006099"], "go")
    multi = [s for s in res["subsumers"] if len(s["labels"]) > 1]
    assert multi, "expected at least one term with two labels"


def test_seed_cap_raises(t):
    ug = Ubergraph(t)
    with pytest.raises(SeedLimitExceeded, match="exceeds"):
        ug.common_ancestors(["UBERON:0000964"] * (MAX_SEEDS + 1), "uberon")


def test_empty_seeds_rejected(t):
    with pytest.raises(ValueError, match="no seeds"):
        Ubergraph(t).common_ancestors([], "uberon")


def test_unknown_predicate_rejected(t):
    with pytest.raises(ValueError, match="unknown predicate"):
        Ubergraph(t).common_ancestors(["UBERON:0000964"], "uberon", predicates=("foo",))


# ---- bounding discipline ------------------------------------------------


def test_queries_never_bound_by_a_prefix_filter(t):
    """Measured: the same query takes 0.65-1.34s graph-scoped, 76s unscoped, and
    times out at 120s unscoped with a trailing STRSTARTS filter. The prefix
    filter is slower than no filter at all."""
    ug = Ubergraph(t)
    ug.common_ancestors(["UBERON:0000964", "UBERON:0001811"], "uberon")
    ug.relations("UBERON:0000966", "part_of", "in", target_ontology="cl")
    for call in t.calls:
        q = call.get("query", "")
        assert "STRSTARTS" not in q.upper()


# The only query in the package that is not bound: listing the named graphs.
# Unavoidable, and cheap (0.42s measured). Spelled out here so that any *other*
# unbounded query fails the suite.
GRAPH_LISTING = "SELECT DISTINCT ?g WHERE { GRAPH ?g { ?s ?p ?o } }"


def test_every_graph_query_is_bound_in_its_first_pattern(t):
    ug = Ubergraph(t)
    ug.named_graphs()
    ug.common_ancestors(["UBERON:0000964", "UBERON:0001811"], "uberon")
    ug.relations("UBERON:0000966", "part_of", "in", target_ontology="cl")
    ug.cohort("hsapdv", label_contains="week")
    unbound = []
    for call in t.calls:
        q = call.get("query")
        if not q or GRAPH_LISTING in q:
            continue
        if "VALUES" not in q and "GRAPH <http://purl.obolibrary.org/obo/" not in q:
            unbound.append(q.strip()[:200])
    assert not unbound, "unbounded query/queries: " + " || ".join(unbound)


def test_ontology_restriction_uses_is_defined_by(t):
    ug = Ubergraph(t)
    ug.common_ancestors(["UBERON:0000964", "UBERON:0001811"], "uberon")
    assert any("rdfs:isDefinedBy" in c.get("query", "") for c in t.calls)


def test_obsolete_terms_are_filtered(t):
    ug = Ubergraph(t)
    ug.common_ancestors(["UBERON:0000964", "UBERON:0001811"], "uberon")
    ug.cohort("hsapdv", label_contains="week")
    graph_calls = [c for c in t.calls if "query" in c and "SELECT ?anc ?x" in c["query"]]
    assert graph_calls
    for c in graph_calls:
        assert "owl:deprecated" in c["query"]


# ---- relations and cohort -----------------------------------------------


def test_relations_cross_ontology(t):
    res = Ubergraph(t).relations("UBERON:0000966", "part_of", "in", target_ontology="cl")
    assert res["total"] > 40
    assert "CL:0000573" in {x["curie"] for x in res["terms"]}


def test_relations_direction_validated(t):
    with pytest.raises(ValueError, match="direction"):
        Ubergraph(t).relations("UBERON:0000966", "part_of", "sideways")


def test_cohort_reads_a_naming_convention(t):
    res = Ubergraph(t).cohort("hsapdv", label_contains="week")
    labels = [lab for x in res["terms"] for lab in x["labels"]]
    assert any("week post-fertilization stage" in lab for lab in labels)


def test_cohort_requires_exactly_one_mode(t):
    ug = Ubergraph(t)
    with pytest.raises(ValueError, match="exactly one"):
        ug.cohort("hsapdv")
    with pytest.raises(ValueError, match="exactly one"):
        ug.cohort("hsapdv", sibling_of="HsapDv:0000046", label_contains="week")


def test_missing_ontology_is_an_explicit_error(t):
    with pytest.raises(ValueError, match="not in Ubergraph"):
        Ubergraph(t).cohort("efo", label_contains="week")


# ---- CLI envelope -------------------------------------------------------


def test_cli_envelope_is_stable(monkeypatch, capsys):
    monkeypatch.setattr("onto_query.cli.Transport", lambda **kw: ReplayTransport())
    assert cli_main(["lexical", "-q", "skin", "-o", "uberon", "--probes", "exact"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert set(out) == {"tool", "version", "command", "backend", "params", "warnings", "result"}
    assert out["tool"] == "onto-query"
    assert out["command"] == "lexical"
    assert out["backend"] == "ols4"


def test_cli_warns_when_part_of_is_dropped(monkeypatch, capsys):
    monkeypatch.setattr("onto_query.cli.Transport", lambda **kw: ReplayTransport())
    cli_main(
        [
            "common-ancestors",
            "-s",
            "UBERON:0000964",
            "-s",
            "UBERON:0001811",
            "-t",
            "uberon",
            "--predicates",
            "subClassOf",
        ]
    )
    out = json.loads(capsys.readouterr().out)
    assert any("part_of is not in the predicate set" in w for w in out["warnings"])


def test_cli_does_not_warn_about_near_misses_on_tiny_seed_sets(monkeypatch, capsys):
    """With two seeds, missing one is not a near miss."""
    monkeypatch.setattr("onto_query.cli.Transport", lambda **kw: ReplayTransport())
    cli_main(["common-ancestors", "-s", "UBERON:0000964", "-s", "UBERON:0001811", "-t", "uberon"])
    out = json.loads(capsys.readouterr().out)
    assert out["warnings"] == []


def test_cli_reports_errors_as_json_and_nonzero(monkeypatch, capsys):
    monkeypatch.setattr("onto_query.cli.Transport", lambda **kw: ReplayTransport())
    code = cli_main(["cohort", "-o", "efo", "--label-contains", "week"])
    out = json.loads(capsys.readouterr().out)
    assert code == 2
    assert "not in Ubergraph" in out["error"]


# ---- cross-references ---------------------------------------------------


def test_xrefs_resolve_against_the_store(t):
    """An OBO xref is a literal. Ubergraph holds the target ontologies, so the
    literal can be joined back to a real class and given a label."""
    res = Ubergraph(t).xrefs("UBERON:0010409")
    by_value = {x["value"]: x for x in res["xrefs"]}
    assert by_value["MA:0002486"]["resolved"]["curie"] == "MA:0002486"
    assert by_value["MA:0002486"]["labels"] == ["eye surface"]
    assert by_value["EMAPA:35336"]["labels"] == ["eye surface region"]
    assert res["unresolved"] == []


def test_unresolvable_xrefs_are_reported_not_dropped(t):
    """ICD, GARD and MedDRA are not in Ubergraph. That is worth knowing rather
    than silently omitting."""
    res = Ubergraph(t).xrefs("MONDO:0007739")
    assert len(res["unresolved"]) > 10
    assert any(x.startswith("ICD") for x in res["unresolved"])
    assert all(by["resolved"] is None for by in res["xrefs"] if by["value"] in res["unresolved"])


def test_skos_mappings_are_kept_apart_from_xrefs(t):
    """xrefs are pointers; SKOS mappings are assertions the source ontology
    made. Conflating them would overstate what an xref means."""
    uberon = Ubergraph(t).xrefs("UBERON:0010409")
    assert uberon["mappings"] == {}

    mondo = Ubergraph(t).xrefs("MONDO:0007739")
    assert len(mondo["mappings"]["exactMatch"]) == 11
    assert len(mondo["mappings"]["closeMatch"]) == 1


def test_xref_queries_stay_bound(t):
    """The tidy-looking single query -- BIND an IRI inside an OPTIONAL and look
    up its label -- is a trap: Blazegraph may evaluate the label pattern first
    and scan every label in the store. It read 2.4GB before dying."""
    Ubergraph(t).xrefs("MONDO:0007739")
    for call in t.calls:
        q = call.get("query")
        if not q:
            continue
        assert "BIND(IRI(" not in q.replace(" ", "")
        assert "VALUES" in q


def test_linked_entities_supply_urls_and_registry(t):
    from onto_query.ols import linked_entities

    linked = linked_entities(t, "uberon", "UBERON:0010409")
    ma = linked["MA:0002486"]
    assert ma["url"].startswith("http")
    assert "db-xrefs.yaml" in ma["registry"]
    assert ma["label"] == "eye surface"


def test_cli_xrefs_warns_when_there_are_no_skos_mappings(monkeypatch, capsys):
    monkeypatch.setattr("onto_query.cli.Transport", lambda **kw: ReplayTransport())
    cli_main(["xrefs", "UBERON:0010409", "-o", "uberon"])
    out = json.loads(capsys.readouterr().out)
    assert any("not logical assertions of equivalence" in w for w in out["warnings"])
    assert out["result"]["xrefs"][0]["url"].startswith("http")


# ---- reaching ontologies Ubergraph does not hold ------------------------


def test_local_is_omitted_when_the_ontology_has_no_preferred_prefix(t):
    """OLS4's local=true filters on the preferred prefix. EHDAA2 declares none,
    so the flag matches nothing and turns every search into zero hits -- a
    silent wrong answer rather than an error."""
    from onto_query.ols import search_config

    assert search_config(t, "uberon")["supports_local"] is True
    assert search_config(t, "ehdaa2")["supports_local"] is False

    res = lexical(t, "liver", "ehdaa2", probes=("exact",))
    assert res["scoped_locally"] is False
    assert [h["curie"] for h in res["hits"]] == ["EHDAA2:0000997"]
    assert "local" not in t.calls[-1]["params"]


def test_crosswalk_bridges_into_ubergraph(t):
    """EHDAA2 is not in Ubergraph, but Uberon cross-references it, so an EHDAA2
    identifier still reaches a Uberon term."""
    res = Ubergraph(t).crosswalk("EHDAA2:0000997", "uberon")
    assert res["total"] == 1
    assert res["terms"][0]["curie"] == "UBERON:0002107"
    assert res["terms"][0]["labels"] == ["liver"]


def test_crosswalk_matches_a_typed_literal(t):
    """The xrefs are xsd:string-typed and Blazegraph does not equate a plain
    literal with one. Matching "EHDAA2:0000997" returns zero rows; the typed
    form returns the hit. FILTER(STR(?x) = ...) also works but is unbound --
    69s against 0.56s."""
    Ubergraph(t).crosswalk("EHDAA2:0000997", "uberon")
    q = t.calls[-1]["query"]
    assert '"EHDAA2:0000997"^^xsd:string' in q
    assert "FILTER(STR(" not in q.replace(" ", "")


def test_crosswalk_can_return_several_ontologies(t):
    res = Ubergraph(t).crosswalk("EMAPA:16846")
    assert {d["curie"] for d in res["terms"]} == {"MA:0000358", "UBERON:0002107"}


def test_crosswalk_miss_is_empty_not_an_error(t):
    res = Ubergraph(t).crosswalk("NOSUCH:9999999", "uberon")
    assert res["total"] == 0
    assert res["terms"] == []


def test_crosswalk_rejects_an_identifier_that_would_break_the_query(t):
    with pytest.raises(ValueError, match="not a usable identifier"):
        Ubergraph(t).crosswalk('EHDAA2:1" . ?x ?y ?z . #', "uberon")


def test_cli_warns_when_local_scoping_is_unavailable(monkeypatch, capsys):
    monkeypatch.setattr("onto_query.cli.Transport", lambda **kw: ReplayTransport())
    cli_main(["lexical", "-q", "liver", "-o", "ehdaa2", "--probes", "exact"])
    out = json.loads(capsys.readouterr().out)
    assert any("declares no preferred prefix" in w for w in out["warnings"])


def test_cli_crosswalk_always_flags_that_an_xref_is_not_equivalence(monkeypatch, capsys):
    monkeypatch.setattr("onto_query.cli.Transport", lambda **kw: ReplayTransport())
    cli_main(["crosswalk", "EHDAA2:0000997", "-t", "uberon"])
    out = json.loads(capsys.readouterr().out)
    assert any("not an assertion of equivalence" in w for w in out["warnings"])


# ---- relations for ontologies outside Ubergraph -------------------------


def test_neighbours_finds_cross_ontology_edges_ubergraph_cannot(t):
    """EHDAA2 is OLS4-only. Its staging link into HsapDv exists nowhere else."""
    from onto_query.ols import neighbours

    res = neighbours(t, "ehdaa2", "EHDAA2:0000997")
    assert res["label"] == "liver"
    starts = res["outgoing"]["existence starts during or after"]
    assert starts == [{"curie": "HsapDv:0000019", "label": "CS12"}]
    assert res["external_targets"] == ["AEO", "CARO", "HsapDv"]


def test_neighbours_separates_direction(t):
    from onto_query.ols import neighbours

    res = neighbours(t, "ehdaa2", "EHDAA2:0000997")
    assert "EHDAA2:0000998" in {d["curie"] for d in res["outgoing"]["part of"]}
    assert "EHDAA2:0001000" in {d["curie"] for d in res["incoming"]["part of"]}


def test_neighbours_double_encodes_the_iri(t):
    """Single-encoding the IRI in the path returns HTTP 400."""
    from onto_query.ols import neighbours

    neighbours(t, "ehdaa2", "EHDAA2:0000997")
    call = next(c for c in t.calls if c.get("backend") == "ols4-graph")
    assert call["iri"] == "http://purl.obolibrary.org/obo/EHDAA2_0000997"


def test_cli_neighbours_says_what_it_cannot_do(monkeypatch, capsys):
    monkeypatch.setattr("onto_query.cli.Transport", lambda **kw: ReplayTransport())
    cli_main(["neighbours", "EHDAA2:0000997", "-o", "ehdaa2"])
    out = json.loads(capsys.readouterr().out)
    assert any("no closure, no information content" in w for w in out["warnings"])
    assert any("HsapDv" in w for w in out["warnings"])


def test_hierarchy_separates_subsumption_from_part_of(t):
    """EHDAA2 liver has no subclasses but 26 parts. A subsumption-only answer
    would say it has no descendants at all."""
    from onto_query.ols import hierarchy

    down = hierarchy(t, "ehdaa2", "EHDAA2:0000997", "down")
    assert down["subsumption"]["total"] == 0
    assert down["hierarchical"]["total"] == 26
    extra = {d["curie"] for d in down["hierarchical"]["reached_only_via_other_relations"]}
    assert "EHDAA2:0000308" in extra

    up = hierarchy(t, "ehdaa2", "EHDAA2:0000997", "up")
    assert (up["subsumption"]["total"], up["hierarchical"]["total"]) == (8, 19)


def test_hierarchy_subsumption_only_skips_the_second_call(t):
    from onto_query.ols import hierarchy

    res = hierarchy(t, "ehdaa2", "EHDAA2:0000997", "up", subsumption_only=True)
    assert "hierarchical" not in res
    assert all(c["relation"] == "ancestors" for c in t.calls if c.get("relation"))


def test_hierarchy_direction_validated(t):
    from onto_query.ols import hierarchy

    with pytest.raises(ValueError, match="direction"):
        hierarchy(t, "ehdaa2", "EHDAA2:0000997", "sideways")


def test_cli_hierarchy_flags_part_of_only_terms(monkeypatch, capsys):
    monkeypatch.setattr("onto_query.cli.Transport", lambda **kw: ReplayTransport())
    cli_main(["hierarchy", "EHDAA2:0000997", "-o", "ehdaa2", "-d", "down"])
    out = json.loads(capsys.readouterr().out)
    assert any("reached only via part_of" in w for w in out["warnings"])


# ---- release checks -----------------------------------------------------

import datetime as _dt
import os

from onto_query import releases

TODAY = _dt.date(2026, 10, 3)


@pytest.fixture
def cache(tmp_path) -> Path:
    return tmp_path / "releases.json"


def test_release_reports_both_backends_and_their_agreement(t, cache):
    r = releases.check(t, "hsapdv", cache_path=cache, today=TODAY)
    assert r["ols4"]["version"] == r["ubergraph"]["version"]
    assert r["agree"] is True
    assert r["from_cache"] is False
    assert r["warnings"] == []


def test_absent_from_ubergraph_is_not_disagreement(t, cache):
    """False must mean the backends serve different releases. An ontology
    Ubergraph never had is a different problem with a different fix."""
    r = releases.check(t, "ehdaa2", cache_path=cache, today=TODAY)
    assert r["ubergraph"]["present"] is False
    assert r["agree"] is None
    assert any("not in Ubergraph" in w for w in r["warnings"])


def test_disagreement_is_warned_not_just_flagged(t, cache, monkeypatch):
    monkeypatch.setattr(
        releases,
        "ubergraph_release",
        lambda ug, o: {"version": "2024-01-01", "version_iri": None, "graph": "g", "present": True},
    )
    r = releases.check(t, "hsapdv", cache_path=cache, today=TODAY)
    assert r["agree"] is False
    assert any(w.startswith("BACKENDS DISAGREE") for w in r["warnings"])


def test_same_day_recheck_is_served_from_cache(t, cache):
    releases.check(t, "hsapdv", cache_path=cache, today=TODAY)
    calls = len(t.calls)
    again = releases.check(t, "hsapdv", cache_path=cache, today=TODAY)
    assert again["from_cache"] is True
    assert again["cache_age_days"] == 0
    assert len(t.calls) == calls, "a same-day recheck must not touch the network"


def test_cache_expires_the_next_day(t, cache):
    releases.check(t, "hsapdv", cache_path=cache, today=TODAY)
    calls = len(t.calls)
    later = releases.check(t, "hsapdv", cache_path=cache, today=TODAY + _dt.timedelta(days=1))
    assert later["from_cache"] is False
    assert len(t.calls) > calls


def test_refresh_overrides_a_fresh_entry(t, cache):
    releases.check(t, "hsapdv", cache_path=cache, today=TODAY)
    calls = len(t.calls)
    r = releases.check(t, "hsapdv", cache_path=cache, today=TODAY, refresh=True)
    assert r["from_cache"] is False
    assert len(t.calls) > calls


def test_a_release_that_moved_is_reported_against_the_last_check(t, cache, monkeypatch):
    releases.check(t, "hsapdv", cache_path=cache, today=TODAY)
    monkeypatch.setattr(
        releases,
        "ols4_release",
        lambda tr, o: {
            "version": "2026-02-02",
            "version_iri": None,
            "loaded": None,
            "present": True,
        },
    )
    monkeypatch.setattr(
        releases,
        "ubergraph_release",
        lambda ug, o: {"version": "2026-02-02", "version_iri": None, "graph": "g", "present": True},
    )
    r = releases.check(t, "hsapdv", cache_path=cache, today=TODAY + _dt.timedelta(days=30))
    assert r["previous"]["checked"] == "2026-10-03"
    assert r["previous"]["changed"]["ols4"] == ("2025-01-23", "2026-02-02")
    assert any("release changed since the last check" in w for w in r["warnings"])


def test_expect_flags_a_stale_written_reference(t, cache):
    ok = releases.check(t, "hsapdv", cache_path=cache, today=TODAY, expect="2025-01-23")
    assert ok["matches_expected"] is True
    stale = releases.check(t, "hsapdv", cache_path=cache, today=TODAY, expect="2024-01-01")
    assert stale["matches_expected"] is False
    assert any("may be stale" in w for w in stale["warnings"])


def test_a_damaged_cache_costs_a_request_not_the_answer(t, cache):
    cache.write_text("{ this is not json")
    r = releases.check(t, "hsapdv", cache_path=cache, today=TODAY)
    assert r["agree"] is True


def test_an_unwritable_cache_warns_and_still_answers(t, tmp_path):
    blocked = tmp_path / "file" / "releases.json"
    blocked.parent.write_text("not a directory")
    r = releases.check(t, "hsapdv", cache_path=blocked, today=TODAY)
    assert r["agree"] is True
    assert any("could not write the release cache" in w for w in r["warnings"])


def test_cache_default_honours_the_env_override(monkeypatch, tmp_path):
    monkeypatch.setenv(releases.CACHE_ENV, str(tmp_path / "x.json"))
    assert releases.default_cache_path() == tmp_path / "x.json"


@pytest.mark.parametrize(
    ("os_name", "env", "expected"),
    [
        ("posix", {"XDG_STATE_HOME": "/s"}, "/s"),
        ("posix", {}, "/home/u/.local/state"),
        ("nt", {"LOCALAPPDATA": r"C:\Users\u\AppData\Local"}, r"C:\Users\u\AppData\Local"),
        # Windows without LOCALAPPDATA set; os.path.join is posix-flavoured
        # here, which is fine -- the branch, not the separator, is the point.
        ("nt", {}, os.path.join("/home/u", "AppData", "Local")),
    ],
)
def test_state_base_per_platform(os_name, env, expected):
    assert releases.state_base(os_name, env, "/home/u") == expected


def test_cache_default_is_under_the_state_dir(monkeypatch, tmp_path):
    monkeypatch.delenv(releases.CACHE_ENV, raising=False)
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    assert releases.default_cache_path() == tmp_path / "onto-query" / "releases.json"


def test_version_falls_back_to_the_date_in_the_version_iri():
    """Not every ontology asserts owl:versionInfo, but OBO release IRIs are dated."""
    iri = "http://purl.obolibrary.org/obo/uberon/releases/2026-06-19/uberon.owl"
    assert releases._version_from_iri(iri) == "2026-06-19"
    assert releases._version_from_iri("http://example.org/undated.owl") is None
    assert releases._version_from_iri(None) is None


def test_release_cli_envelope(t, cache, monkeypatch, capsys):
    monkeypatch.setenv(releases.CACHE_ENV, str(cache))
    monkeypatch.setattr("onto_query.cli.Transport", lambda **kw: t)
    assert cli_main(["release", "-o", "hsapdv"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["command"] == "release"
    assert out["backend"] == "ols4+ubergraph"
    assert out["result"]["agree"] is True
    assert "warnings" not in out["result"], "warnings belong in the envelope, once"
