"""`gene-id check`: existence, official symbol, species and provenance, all
against faked lookups so it runs offline."""

from __future__ import annotations

import copy
import json
import urllib.error

import pytest
from gene_identity import check, cli, translator
from gene_identity.check import Store

# NodeNorm, as far as these tests need it. A replaced ID answers with its
# successor; an unknown one with nothing.
GENES = {
    "NCBIGene:13488": {"ncbi_gene_id": "NCBIGene:13488", "label": "Drd1", "taxon": "NCBITaxon:10090"},
    "NCBIGene:13370": {"ncbi_gene_id": "NCBIGene:13370", "label": "Dio1", "taxon": "NCBITaxon:10090"},
    "NCBIGene:1812": {"ncbi_gene_id": "NCBIGene:1812", "label": "DRD1", "taxon": "NCBITaxon:9606"},
    "NCBIGene:83839": {"ncbi_gene_id": "NCBIGene:83839", "label": "Calb1", "taxon": "NCBITaxon:10116"},
    "NCBIGene:20604": {"ncbi_gene_id": "NCBIGene:20604", "label": "Sst", "taxon": "NCBITaxon:10090"},
    "NCBIGene:234725": {"ncbi_gene_id": "NCBIGene:234725", "label": "Grhl3", "taxon": "NCBITaxon:10090"},
    "NCBIGene:99000001": {"ncbi_gene_id": "NCBIGene:13488", "label": "Drd1", "taxon": "NCBITaxon:10090"},
}
LINEAGE = {
    "NCBITaxon:10090": ["NCBITaxon:10090", "NCBITaxon:862507", "NCBITaxon:39107", "NCBITaxon:9989"],
    "NCBITaxon:10116": ["NCBITaxon:10116", "NCBITaxon:10114", "NCBITaxon:39107", "NCBITaxon:9989"],
    "NCBITaxon:9606": ["NCBITaxon:9606", "NCBITaxon:9605", "NCBITaxon:9443"],
}

D1 = {"name": "D1", "taxon": "NCBITaxon:10090", "outcome": "GENE",
      "ncbi_gene_id": "NCBIGene:13488", "symbol": "Drd1", "gene_taxon": "NCBITaxon:10090",
      "method": "PAPER_DEFINITION", "rationale": "dopamine D1 receptor"}
CB = {"name": "CB", "taxon": "NCBITaxon:39107", "outcome": "GENE",                 # Murinae
      "ncbi_gene_id": "NCBIGene:83839", "symbol": "Calb1", "gene_taxon": "NCBITaxon:10116",
      "method": "PAPER_DEFINITION", "rationale": "calbindin, rat"}
SOM = {"name": "SOM", "taxon": "NCBITaxon:10090", "outcome": "UNRESOLVED", "kind": "AMBIGUOUS",
       "claimants": [{"ncbi_gene_id": "NCBIGene:20604", "symbol": "Sst"},
                     {"ncbi_gene_id": "NCBIGene:234725", "symbol": "Grhl3"}],
       "rationale": "no context"}
FAMILY = {"name": "CaMKII", "taxon": "NCBITaxon:10090", "outcome": "NO_SINGLE_GENE",
          "kind": "GENE_FAMILY", "rationale": "four genes"}


class World:
    """Fake lookups that count their calls, and can be switched off."""

    def __init__(self):
        self.gene_calls: list[list[str]] = []
        self.lineage_calls: list[str] = []
        self.down = False

    def genes(self, ids):
        self.gene_calls.append(ids)
        if self.down:
            raise urllib.error.URLError("down")
        return {i: GENES.get(i) for i in ids}

    def lineage(self, taxon):
        self.lineage_calls.append(taxon)
        if self.down:
            raise TimeoutError("down")
        return LINEAGE.get(taxon, [])


@pytest.fixture
def world():
    return World()


def store(tmp_path, world, *, resolved=tuple(GENES)) -> Store:
    d = tmp_path / "cache"
    check.log_resolved([{"name": "x", "gene": {"ncbi_gene_id": i}} for i in resolved], directory=d)
    return Store(directory=d, lookup_genes=world.genes, lookup_lineage=world.lineage)


def with_(rec, **kw):
    out = copy.deepcopy(rec)
    out.update(kw)
    return out


def run(records, tmp_path, world, **kw):
    return check.check(records, store(tmp_path, world, **kw))


def test_clean_records_pass(tmp_path, world):
    assert run([D1, CB, SOM, FAMILY], tmp_path, world) == ([], [])


def test_a_gene_of_a_descendant_species_is_within_a_higher_taxon(tmp_path, world):
    assert run([CB], tmp_path, world) == ([], [])
    assert world.lineage_calls == ["NCBITaxon:10116"]


def test_schema_problems_stop_the_check_before_any_lookup(tmp_path, world):
    problems, _ = run([with_(D1, ncbi_gene_id=None)], tmp_path, world)
    assert problems and "ncbi_gene_id" in problems[0]
    assert world.gene_calls == []


@pytest.mark.parametrize("rec, fragment", [
    (with_(D1, ncbi_gene_id="NCBIGene:424242"), "does not resolve to an NCBI gene"),
    (with_(D1, ncbi_gene_id="NCBIGene:99000001"), "NodeNormalization gives NCBIGene:13488"),
    (with_(D1, symbol="D1"), "symbol 'D1': NCBIGene:13488 is 'Drd1'"),
    (with_(D1, symbol="DRD1"), "symbol 'DRD1'"),                         # human style, mouse gene
    (with_(D1, ncbi_gene_id="NCBIGene:13370"), "is 'Dio1'"),              # ID changed, symbol not
    (with_(D1, gene_taxon="NCBITaxon:10116"), "is a NCBITaxon:10090 gene"),
    (with_(D1, ncbi_gene_id="NCBIGene:1812", symbol="DRD1", gene_taxon="NCBITaxon:9606"),
     "outside the record's taxon NCBITaxon:10090"),
    (with_(SOM, claimants=[{"ncbi_gene_id": "NCBIGene:20604", "symbol": "SOM"},
                           {"ncbi_gene_id": "NCBIGene:234725", "symbol": "Grhl3"}]),
     "claimants[0].symbol 'SOM'"),
    (with_(SOM, claimants=[{"ncbi_gene_id": "NCBIGene:20604", "symbol": "Sst"},
                           {"ncbi_gene_id": "NCBIGene:424242", "symbol": "Foo"}]),
     "claimants[1].ncbi_gene_id NCBIGene:424242 does not resolve"),
])
def test_each_claim_is_checked(tmp_path, world, rec, fragment):
    problems, unchecked = run([FAMILY, rec], tmp_path, world)
    assert unchecked == []
    assert any(fragment in p for p in problems), problems
    assert all(p.startswith(f"[1] ({rec['name']})") for p in problems), problems


def test_an_id_never_returned_by_resolve_is_flagged(tmp_path, world):
    resolved = [i for i in GENES if i != "NCBIGene:13488"]
    problems, _ = run([D1], tmp_path, world, resolved=resolved)
    assert len(problems) == 1 and "never returned by `gene-id resolve`" in problems[0]
    # ... and only that: the ID is otherwise right.
    s = store(tmp_path, world, resolved=resolved)
    assert check.check([D1], s, provenance=False) == ([], [])


def test_lookup_failures_are_unchecked_not_problems(tmp_path, world):
    world.down = True
    problems, unchecked = run([D1, CB], tmp_path, world)
    assert problems == []
    assert len(unchecked) == 2 and all("unreachable" in u for u in unchecked)


def test_a_lineage_failure_leaves_only_the_species_unchecked(tmp_path, world):
    s = store(tmp_path, world)
    s.get_genes({"NCBIGene:83839"})      # cached while up
    world.down = True
    problems, unchecked = check.check([CB], s)
    assert problems == [] and len(unchecked) == 1 and "NCBI Taxonomy" in unchecked[0]


def test_lookups_are_cached_and_misses_are_not(tmp_path, world):
    s = store(tmp_path, world)
    check.check([D1, CB, with_(D1, ncbi_gene_id="NCBIGene:424242")], s)
    again = Store(directory=s.directory, lookup_genes=world.genes, lookup_lineage=world.lineage)
    world.gene_calls.clear()
    world.lineage_calls.clear()
    check.check([D1, CB], again)
    assert world.gene_calls == [] and world.lineage_calls == []
    check.check([with_(D1, ncbi_gene_id="NCBIGene:424242")], again)
    assert world.gene_calls == [["NCBIGene:424242"]]          # asked again


def test_offline_store_uses_caches_only(tmp_path, world):
    s = store(tmp_path, world)
    s.offline = True
    problems, unchecked = check.check([D1], s)
    assert problems == [] and len(unchecked) == 1 and world.gene_calls == []


def test_ncbi_lineage_parses_efetch(monkeypatch):
    xml = b"""<TaxaSet><Taxon><TaxId>10090</TaxId><LineageEx>
      <Taxon><TaxId>9989</TaxId></Taxon><Taxon><TaxId>39107</TaxId></Taxon>
      </LineageEx></Taxon></TaxaSet>"""

    class Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return xml

    monkeypatch.setattr(check.urllib.request, "urlopen", lambda url, timeout: Resp())
    assert check.ncbi_lineage("NCBITaxon:10090") == [
        "NCBITaxon:10090", "NCBITaxon:9989", "NCBITaxon:39107"]


# ── The resolve log and the CLI ──────────────────────────────────────────────


def test_resolve_logs_every_id_it_prints(monkeypatch, capsys):
    monkeypatch.setattr(translator, "nameres_lookup", lambda name, taxon, **kw: [
        {"ncbi_gene_id": "NCBIGene:20604", "label": "Sst", "taxa": []},
        {"ncbi_gene_id": "NCBIGene:234725", "label": "Grhl3", "taxa": []},
        {"ncbi_gene_id": "NCBIGene:5", "label": "Other", "taxa": []}])
    monkeypatch.setattr(translator, "nameres_synonyms", lambda ids, **kw: {
        "NCBIGene:20604": ["SOM"], "NCBIGene:234725": ["SOM"], "NCBIGene:5": []})
    assert cli.main(["resolve", "--taxon", "NCBITaxon:10090", "SOM"]) == 0
    capsys.readouterr()
    log = json.loads((check.cache_dir() / "resolved.json").read_text())
    assert set(log) == {"NCBIGene:20604", "NCBIGene:234725", "NCBIGene:5"}
    assert log["NCBIGene:20604"]["name"] == "SOM"


def _file(tmp_path, records):
    f = tmp_path / "x.gene-records.json"
    f.write_text(json.dumps(records))
    return f


def test_cli_check_flags_with_exit_2(tmp_path, monkeypatch, capsys):
    check.log_resolved([{"gene": {"ncbi_gene_id": "NCBIGene:13488"}}])
    f = _file(tmp_path, [with_(D1, symbol="D1")])
    s = Store(lookup_genes=World().genes, lookup_lineage=World().lineage)
    monkeypatch.setattr(check, "Store", lambda offline=False: s)
    assert cli.main(["check", str(f)]) == 2
    assert "symbol 'D1'" in capsys.readouterr().err


def test_cli_check_reports_unchecked_and_exits_0(tmp_path, monkeypatch, capsys):
    s = Store(lookup_genes=World().genes, lookup_lineage=World().lineage, offline=True)
    check.log_resolved([{"gene": {"ncbi_gene_id": "NCBIGene:13488"}}])
    s.resolved = {"NCBIGene:13488": {}}
    monkeypatch.setattr(check, "Store", lambda offline=False: s)
    assert cli.main(["check", str(_file(tmp_path, [D1]))]) == 0
    io = capsys.readouterr()
    assert "UNCHECKED NCBIGene:13488" in io.err and "1 unchecked" in io.out


def test_cli_check_unreadable_exits_1(tmp_path):
    assert cli.main(["check", str(tmp_path / "missing.gene-records.json")]) == 1
