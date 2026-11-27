"""The NLM-Gene converter, the metrics, and the committed snapshot."""

from __future__ import annotations

import hashlib
import json
from importlib import resources

import pytest
from gene_identity_eval import cli, data, metrics, nlm_gene

XML = """<?xml version='1.0' encoding='UTF-8'?><collection><source>PubTator</source>
<document><id>111</id>
<passage><infon key="type">title</infon><offset>0</offset><text>Wnt signalling and Pax7 in mouse muscle.</text>
<annotation id="0"><infon key="NCBI Gene identifier">22410,22411</infon><infon key="type">STARGENE</infon><location offset="0" length="3"/><text>Wnt</text></annotation>
<annotation id="1"><infon key="NCBI Gene identifier">18509</infon><infon key="type">GENERIF</infon><location offset="19" length="4"/><text>Pax7</text></annotation>
</passage>
<passage><infon key="type">abstract</infon><offset>41</offset><text>Satellite cells express Pax7. We studied ERK1/2 and OVA. Pax7 again.</text>
<annotation id="2"><infon key="NCBI Gene identifier">18509</infon><infon key="type">Gene</infon><location offset="65" length="4"/><text>Pax7</text></annotation>
<annotation id="3"><infon key="NCBI Gene identifier">26417;26413</infon><infon key="type">Gene</infon><location offset="82" length="6"/><text>ERK1/2</text></annotation>
<annotation id="4"><infon key="type">Other</infon><location offset="93" length="3"/><text>OVA</text></annotation>
<annotation id="5"><infon key="NCBI Gene identifier">29875-222</infon><infon key="type">Gene</infon><location offset="98" length="4"/><text>Pax7</text></annotation>
<annotation id="6"><infon key="NCBI Gene identifier">999</infon><infon key="type">Gene</infon><location offset="98" length="4"/><text>Gone</text></annotation>
<annotation id="7"><infon key="NCBI Gene identifier">777</infon><infon key="type">Gene</infon><location offset="98" length="4"/><text>Merged</text></annotation>
</passage></document></collection>"""

M = "NCBITaxon:10090"
GENES = {
    "NCBIGene:22410": {"ncbi_gene_id": "NCBIGene:22410", "label": "Wnt1", "taxon": M},
    "NCBIGene:22411": {"ncbi_gene_id": "NCBIGene:22411", "label": "Wnt2", "taxon": M},
    "NCBIGene:18509": {"ncbi_gene_id": "NCBIGene:18509", "label": "Pax7", "taxon": M},
    "NCBIGene:999": None,
    "NCBIGene:777": {"ncbi_gene_id": "NCBIGene:18509", "label": "Pax7", "taxon": M},
}


@pytest.fixture
def built():
    return nlm_gene.build_cases([nlm_gene.parse_document(XML)], GENES)


def test_parse_keeps_title_and_passage_relative_offsets():
    doc = nlm_gene.parse_document(XML)
    assert doc.pmid == "111" and doc.title.startswith("Wnt signalling")
    m = doc.mentions[2]
    assert m.passage == "abstract" and m.passage_text[m.offset:m.offset + 4] == "Pax7"


@pytest.mark.parametrize("raw, shape, ids", [
    ("18509", "single", ["NCBIGene:18509"]),
    ("22410,22411", "family", ["NCBIGene:22410", "NCBIGene:22411"]),
    ("22410, 22410", "single", ["NCBIGene:22410"]),     # a repeated ID is one gene
    ("26417;26413", "ellipsis", []),
    ("29875-222", "coded", []),
    ("-222,15978", "coded", []),
    ("", "no_id", []),
    ("abc", "malformed", []),
])
def test_classify(raw, shape, ids):
    assert nlm_gene.classify(raw) == (shape, ids)


def test_sentence_at():
    text = "First one. Second has Pax7 here. Third (x)."
    assert nlm_gene.sentence_at(text, text.index("Pax7")) == "Second has Pax7 here."
    assert nlm_gene.sentence_at(text, 0) == "First one."
    assert nlm_gene.sentence_at(text, len(text) - 2) == "Third (x)."


def test_build_cases_maps_and_excludes(built):
    cases, excluded = built
    assert [(c["input"]["name"], c["expected"]["outcome"]) for c in cases] == [
        ("Wnt", "NO_SINGLE_GENE"), ("Pax7", "GENE"), ("Merged", "GENE")]
    assert excluded == {"ellipsis": 1, "no_id": 1, "coded": 1, "id_not_in_nodenorm": 1,
                        "repeat_in_document": 1}


def test_a_case_is_the_skills_input_plus_the_answer(built):
    wnt, pax7, merged = built[0]
    assert wnt["expected"]["members"] == ["NCBIGene:22410", "NCBIGene:22411"]
    assert pax7["input"] == {
        "name": "Pax7", "taxon": M, "title": "Wnt signalling and Pax7 in mouse muscle.",
        "evidence": {"source": "PMID:111", "text": "Wnt signalling and Pax7 in mouse muscle."}}
    assert pax7["expected"]["accept"] == [{"ncbi_gene_id": "NCBIGene:18509", "symbol": "Pax7"}]
    # A merged ID is scored as its successor, and the remap is recorded.
    assert merged["expected"]["accept"][0]["ncbi_gene_id"] == "NCBIGene:18509"
    assert merged["gold"]["remapped"] == {"NCBIGene:777": "NCBIGene:18509"}
    assert [c["id"] for c in built[0]] == ["nlm-111-01", "nlm-111-02", "nlm-111-03"]


def test_a_mention_that_is_none_of_its_genes_names_is_generic():
    names = {"NCBIGene:18509": ["paired box 7", "Pax-7"]}
    cases, _ = nlm_gene.build_cases([nlm_gene.parse_document(XML)], GENES, names)
    by_name = {c["input"]["name"]: c["expected"].get("generic") for c in cases}
    assert by_name == {"Wnt": None, "Pax7": False, "Merged": True}
    # Without names every single-ID mention is taken to name its gene.
    plain, _ = nlm_gene.build_cases([nlm_gene.parse_document(XML)], GENES)
    assert [c["expected"].get("generic") for c in plain] == [None, False, False]


@pytest.mark.parametrize("mention, label, synonyms, names", [
    ("Pax7", "Pax7", [], True),
    ("PAX-7", "Pax7", [], True),                 # normalised as the lookup normalises
    ("paired box 7", "Pax7", ["paired box 7"], True),
    ("Kinases", "AKT1", ["AKT", "PKB"], False),
])
def test_names_gene(mention, label, synonyms, names):
    assert nlm_gene.names_gene(mention, label, synonyms) is names


def test_mixed_species_family_is_excluded():
    genes = {**GENES, "NCBIGene:22411": {**GENES["NCBIGene:22411"], "taxon": "NCBITaxon:9606"}}
    _, excluded = nlm_gene.build_cases([nlm_gene.parse_document(XML)], genes)
    assert excluded["mixed_or_unknown_species"] == 1


# ── Metrics ──────────────────────────────────────────────────────────────────

GENE_EXP = {"outcome": "GENE", "kind": None, "accept": [{"ncbi_gene_id": "NCBIGene:1"}]}
FAM_EXP = {"outcome": "NO_SINGLE_GENE", "kind": None, "accept": [], "members": ["a", "b"]}


@pytest.mark.parametrize("record, expected, passed", [
    ({"outcome": "GENE", "ncbi_gene_id": "NCBIGene:1"}, GENE_EXP, True),
    ({"outcome": "GENE", "ncbi_gene_id": "NCBIGene:2"}, GENE_EXP, False),
    ({"outcome": "NO_SINGLE_GENE", "kind": "GENE_FAMILY"}, FAM_EXP, True),
    ({"outcome": "NO_SINGLE_GENE", "kind": "PTM_STATE"}, FAM_EXP, True),   # kind unscored here
    ({"outcome": "GENE", "ncbi_gene_id": "NCBIGene:1"}, FAM_EXP, False),
    (None, GENE_EXP, False),
    # A generic mention ("Kinases" -> AKT1) also passes as no single gene...
    ({"outcome": "NO_SINGLE_GENE", "kind": "GENE_FAMILY"}, {**GENE_EXP, "generic": True}, True),
    ({"outcome": "GENE", "ncbi_gene_id": "NCBIGene:1"}, {**GENE_EXP, "generic": True}, True),
    # ... but not as anything else, and a named gene never does.
    ({"outcome": "UNRESOLVED", "kind": "AMBIGUOUS"}, {**GENE_EXP, "generic": True}, False),
    ({"outcome": "NO_SINGLE_GENE", "kind": "GENE_FAMILY"}, {**GENE_EXP, "generic": False}, False),
])
def test_score(record, expected, passed):
    assert metrics.score(record, expected)[0] is passed


def _case(cid, expected, method, gene=None):
    return {"id": cid, "expected": expected,
            "resolver_baseline": {"method": method, "gene": gene, "claimants": []}}


STRAT = [
    _case("e", GENE_EXP, "EXACT_SYMBOL", {"ncbi_gene_id": "NCBIGene:1"}),
    _case("w", GENE_EXP, "UNIQUE_SYNONYM", {"ncbi_gene_id": "NCBIGene:9"}),
    _case("a", GENE_EXP, "AMBIGUOUS"),
    _case("n", GENE_EXP, "NO_MATCH"),
    {"id": "x", "expected": GENE_EXP, "resolver_baseline": {"error": "down"}},
    _case("f", FAM_EXP, "UNIQUE_SYNONYM", {"ncbi_gene_id": "NCBIGene:1"}),
]


def test_stratum():
    assert [metrics.stratum(c) for c in STRAT] == [
        "easy", "lookup_wrong", "lookup_ambiguous", "lookup_no_match", "lookup_no_match", "family"]


def test_select_tier_is_capped_seeded_and_stable():
    many = [_case(f"c{i:03d}", GENE_EXP, "AMBIGUOUS") for i in range(50)] + STRAT
    caps = {"lookup_ambiguous": 5, "easy": 1, "family": 0}
    a = metrics.select_tier(many, caps, seed=1)
    assert a == metrics.select_tier(list(reversed(many)), caps, seed=1)
    assert len(a) == 6 and "e" in a and "f" not in a
    assert a != metrics.select_tier(many, caps, seed=2)


def test_summarise():
    cases = {c["id"]: c for c in STRAT}
    rows = [{"id": "e", "passed": True, "record": {"outcome": "GENE"}},
            {"id": "w", "passed": True, "record": {"outcome": "GENE"}},
            {"id": "a", "passed": False, "record": {"outcome": "UNRESOLVED"}},
            {"id": "f", "passed": True, "record": {"outcome": "NO_SINGLE_GENE"}},
            {"id": "n", "voided": True}]
    s = metrics.summarise(rows, cases)
    assert (s["n_scored"], s["passed"], s["accuracy"]) == (4, 3, 0.75)
    assert s["baseline_accuracy"] == 0.25 and s["lift"] == 0.5
    assert s["gene_id_accuracy"] == round(2 / 3, 4) and s["family_recall"] == 1.0
    assert s["per_stratum"]["lookup_wrong"] == {"n": 1, "passed": 1, "accuracy": 1.0,
                                                "baseline_accuracy": 0.0}
    assert s["voided"] == ["n"]
    assert s["by_name_match"] == {"names_gene": {"n": 3, "passed": 2, "accuracy": round(2 / 3, 4),
                                                 "baseline_accuracy": round(1 / 3, 4)}}
    assert s["passed_by_generic_allowance"] == 0


def test_summarise_counts_passes_that_needed_the_generic_allowance():
    generic = {**GENE_EXP, "generic": True}
    cases = {"g": _case("g", generic, "NO_MATCH"), "h": _case("h", generic, "NO_MATCH")}
    rows = [{"id": "g", "passed": True, "record": {"outcome": "NO_SINGLE_GENE"}},
            {"id": "h", "passed": True, "record": {"outcome": "GENE"}}]
    s = metrics.summarise(rows, cases)
    assert s["passed_by_generic_allowance"] == 1
    assert s["by_name_match"]["generic"]["n"] == 2


def test_summarise_reports_the_refuse_everything_reference():
    generic = {**GENE_EXP, "generic": True}
    cases = {"g": _case("g", generic, "NO_MATCH"), "s": _case("s", GENE_EXP, "NO_MATCH")}
    rows = [{"id": "g", "passed": True, "record": {"outcome": "NO_SINGLE_GENE"}},
            {"id": "s", "passed": False, "record": {"outcome": "NO_SINGLE_GENE"}}]
    s = metrics.summarise(rows, cases)
    assert s["refuse_all_accuracy"] == 0.5  # the generic one only


# ── The committed snapshot ───────────────────────────────────────────────────


def test_snapshot_matches_its_source_record():
    src = data.source()
    assert src["license"] == "cc-zero" and src["doi"] == "10.5061/dryad.dv41ns1wt"
    raw = resources.files("gene_identity_eval").joinpath("data/nlm_gene/cases.jsonl").read_bytes()
    assert hashlib.sha256(raw).hexdigest() == src["cases_sha256"]
    assert src["cases"] == len(data.cases())


def test_every_case_is_well_formed():
    for c in data.cases().values():
        assert set(c["input"]) == {"name", "taxon", "title", "evidence"}
        assert c["input"]["evidence"]["text"], c["id"]
        exp = c["expected"]
        if exp["outcome"] == "GENE":
            assert len(exp["accept"]) == 1 and isinstance(exp["generic"], bool)
        else:
            assert exp["outcome"] == "NO_SINGLE_GENE" and len(exp["members"]) >= 2
        assert "resolver_baseline" in c


def test_tiers_are_reproducible_from_the_cases():
    """A tier is its seed and caps applied to the cases; nothing hand-picked."""
    cases = list(data.cases().values())
    for name, t in data.tiers().items():
        assert t["ids"] == metrics.select_tier(cases, t["caps"], t["seed"]), name


def test_cli_info_and_cases(capsys):
    assert cli.main(["info"]) == 0
    info = json.loads(capsys.readouterr().out)
    assert info["license"] == "cc-zero" and "l4" in info["tiers"]
    assert cli.main(["cases", "--tier", "l4"]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert len(lines) == len(data.tiers()["l4"]["ids"])
