"""Gene tables and name resolution. Ported from evidencell tests/test_gene_identity.py
(Cellular-Semantics/evidencell@7641aab); the KB pin and marker tests stayed there."""

from __future__ import annotations

import gzip
import json
import sqlite3
from pathlib import Path

import pytest
from gene_identity import cli, resolve, table, translator
from gene_identity.resolve import (
    AMBIGUOUS,
    CASE_INSENSITIVE_SYMBOL,
    EXACT_SYMBOL,
    NO_MATCH,
    UNIQUE_SYNONYM,
    GeneIdsUnavailable,
    resolve_names,
)
from gene_identity.table import load_gene_tables, read_gene_ids, write_gene_ids
from gene_identity.translator import normalise_name

_ROWS = [
    # ensembl, stats symbol, ncbi, label, synonyms
    ("ENSMUSG01", "Pvalb", "NCBIGene:19293", "Pvalb", ["PV", "parvalbumin"]),
    ("ENSMUSG02", "Calb1", "NCBIGene:12307", "Calb1", ["CB", "calbindin"]),
    ("ENSMUSG03", "Ctsb", "NCBIGene:13030", "Ctsb", ["CB", "cathepsin B"]),
    ("ENSMUSG04", "Car8", "NCBIGene:12319", "Ca8", ["CA-VIII"]),
    ("ENSMUSG05", "Htr3a", "NCBIGene:15561", "Htr3a", ["5-HT3a", "5HT3A"]),
    ("ENSMUSG06", "Gm1992", None, None, []),
    ("ENSMUSG07", "Sst", "NCBIGene:20604", "Sst", ["SST", "somatostatin"]),
]


def _rows() -> list[dict]:
    return [
        {
            "ensembl_id": e, "stats_symbol": s, "stats_col": i, "ncbi_gene_id": n,
            "label": lab, "taxon": "NCBITaxon:10090" if n else None,
            "equivalent_ids": ["MGI:1"] if n else [], "synonyms": [s, *syn] if n else [],
        }
        for i, (e, s, n, lab, syn) in enumerate(_ROWS)
    ]


def _table(path: Path, rows: list[dict], meta: dict | None = None) -> Path:
    write_gene_ids(path, meta or {}, rows)
    return path


@pytest.fixture
def gene_table(tmp_path: Path) -> Path:
    return _table(tmp_path / "gene_ids.tsv.gz", _rows(), {"dataset_id": "TAX", "source_sha256": "abc"})


@pytest.fixture
def con(gene_table: Path):
    c = sqlite3.connect(":memory:")
    load_gene_tables(c, gene_table)
    yield c
    c.close()


def _con(path: Path) -> sqlite3.Connection:
    c = sqlite3.connect(":memory:")
    load_gene_tables(c, path)
    return c


def test_normalise_name():
    assert normalise_name("5-HT3a") == "5ht3a"
    assert normalise_name("Calbindin D28k") == "calbindind28k"
    assert normalise_name("GAD_67") == "gad67"


def test_gene_ids_round_trip_and_is_deterministic(tmp_path, gene_table):
    meta, rows = read_gene_ids(gene_table)
    assert meta == {"dataset_id": "TAX", "source_sha256": "abc"}
    assert rows[0]["synonyms"] == ["Pvalb", "PV", "parvalbumin"]
    assert rows[5]["ncbi_gene_id"] is None and rows[5]["stats_col"] == 5
    again = tmp_path / "again.tsv.gz"
    write_gene_ids(again, meta, rows)
    assert again.read_bytes() == gene_table.read_bytes()


def test_load_records_provenance_meta(con):
    assert table.gene_ids_meta(con) == {"dataset_id": "TAX", "source_sha256": "abc"}
    assert con.execute("SELECT COUNT(*) FROM genes").fetchone()[0] == len(_ROWS)


def test_missing_table_leaves_tables_empty(tmp_path):
    c = sqlite3.connect(":memory:")
    assert load_gene_tables(c, tmp_path / "nope.tsv.gz") == 0
    with pytest.raises(GeneIdsUnavailable):
        resolve_names(c, ["Pvalb"])


@pytest.mark.parametrize(
    "name, method, symbol",
    [
        ("Pvalb", EXACT_SYMBOL, "Pvalb"),
        ("Car8", EXACT_SYMBOL, "Car8"),            # the dataset's own symbol
        ("Ca8", EXACT_SYMBOL, "Car8"),             # current Translator label
        ("PVALB", CASE_INSENSITIVE_SYMBOL, "Pvalb"),
        ("PV", UNIQUE_SYNONYM, "Pvalb"),
        ("parvalbumin", UNIQUE_SYNONYM, "Pvalb"),
        ("5-HT3a", UNIQUE_SYNONYM, "Htr3a"),
        ("5HT3a", UNIQUE_SYNONYM, "Htr3a"),        # normalised synonym match
        ("Gm1992", EXACT_SYMBOL, "Gm1992"),        # no NCBIGene: Ensembl is the key
        ("SST", CASE_INSENSITIVE_SYMBOL, "Sst"),
    ],
)
def test_resolution_accepts(con, name, method, symbol):
    m = resolve_names(con, [name])[name]
    assert (m.method, m.gene.stats_symbol if m.gene else None) == (method, symbol)


def test_case_insensitive_symbol_beats_another_genes_synonym(tmp_path):
    rows = [*_rows(), {"ensembl_id": "ENSMUSG08", "stats_symbol": "Lmx1a", "stats_col": 7, "ncbi_gene_id": "NCBIGene:110648", "label": "Lmx1a", "taxon": "NCBITaxon:10090", "equivalent_ids": [], "synonyms": ["Lmx1a", "sst"]}]
    c = _con(_table(tmp_path / "t.tsv.gz", rows))
    m = resolve_names(c, ["SST"])["SST"]
    assert (m.method, m.gene.stats_symbol) == (CASE_INSENSITIVE_SYMBOL, "Sst")
    assert [g.stats_symbol for g in m.claimants] == ["Lmx1a"]


def test_two_claimants_are_ambiguous_never_guessed(con):
    m = resolve_names(con, ["CB"])["CB"]
    assert m.method == AMBIGUOUS and m.gene is None
    assert sorted(c.stats_symbol for c in m.claimants) == ["Calb1", "Ctsb"]


def test_no_claimant_is_no_match(con):
    m = resolve_names(con, ["BrdU"])["BrdU"]
    assert m.method == NO_MATCH and m.gene is None and m.claimants == []


@pytest.mark.parametrize("name, method", [("Kiss1", EXACT_SYMBOL),
                                          ("KISS1", CASE_INSENSITIVE_SYMBOL)])
def test_duplicate_symbol_prefers_the_gene_with_an_ncbi_id(tmp_path, name, method):
    rows = [*_rows(), {"ensembl_id": "ENSMUSG09", "stats_symbol": "Kiss1", "stats_col": 7, "ncbi_gene_id": "NCBIGene:280287", "label": "Kiss1", "taxon": "NCBITaxon:10090", "equivalent_ids": [], "synonyms": ["Kiss1"]}, {"ensembl_id": "ENSMUSG10", "stats_symbol": "Kiss1", "stats_col": 8, "ncbi_gene_id": None, "label": None, "taxon": None, "equivalent_ids": [], "synonyms": []}]
    m = resolve_names(_con(_table(tmp_path / "t.tsv.gz", rows)), [name])[name]
    # Duplicate Ensembl models of one locus are one gene, not AMBIGUOUS.
    assert (m.method, m.gene.ensembl_id) == (method, "ENSMUSG09")


def test_resolve_with_table_returns_official_label(gene_table):
    out = resolve.resolve_with_table(["Ca8", "CB"], gene_table)
    assert out[0]["method"] == EXACT_SYMBOL
    assert out[0]["gene"] == {"ncbi_gene_id": "NCBIGene:12319", "symbol": "Car8",
                              "label": "Ca8", "ensembl_id": "ENSMUSG04"}
    assert out[1]["method"] == AMBIGUOUS and len(out[1]["claimants"]) == 2


def test_resolve_with_missing_table_raises(tmp_path):
    with pytest.raises(GeneIdsUnavailable):
        resolve.resolve_with_table(["PV"], tmp_path / "missing.tsv.gz")


# ── Translator clients (HTTP faked) ──────────────────────────────────────────

_NODENORM_PVALB = {
    "id": {"identifier": "ENSEMBL:ENSMUSG00000005716", "label": "Pvalb (Mmus)"},
    "equivalent_identifiers": [
        {"identifier": "NCBIGene:19293", "label": "Pvalb"},
        {"identifier": "ENSEMBL:ENSMUSG00000005716"},
        {"identifier": "MGI:97821", "label": "Pvalb"},
    ],
    "taxa": ["NCBITaxon:10090"],
}


def test_nodenorm_parse():
    assert translator._ncbi_from_nodenorm(_NODENORM_PVALB) == {
        "ncbi_gene_id": "NCBIGene:19293", "label": "Pvalb",
        "taxon": "NCBITaxon:10090", "equivalent_ids": ["MGI:97821"],
    }
    assert translator._ncbi_from_nodenorm(None) is None


def test_nodenorm_label_without_ncbi_drops_taxon_suffix():
    entry = {
        "id": {"identifier": "ENSEMBL:ENSMUSG00000098760", "label": "Gm2164 (Mmus)"},
        "equivalent_identifiers": [{"identifier": "ENSEMBL:ENSMUSG00000098760"}],
    }
    assert translator._ncbi_from_nodenorm(entry)["label"] == "Gm2164"


def test_nodenorm_batches_and_posts_unconflated(monkeypatch):
    calls = []

    def fake(url, payload=None, **kw):
        calls.append((url, payload))
        return {c: (_NODENORM_PVALB if c == "ENSEMBL:A" else None) for c in payload["curies"]}

    monkeypatch.setattr(translator, "_http_json", fake)
    out = translator.nodenorm(["ENSEMBL:A", "ENSEMBL:B", "ENSEMBL:C"], batch=2)
    assert [len(p["curies"]) for _, p in calls] == [2, 1]
    assert all(p["conflate"] is False for _, p in calls)
    assert out["ENSEMBL:A"]["ncbi_gene_id"] == "NCBIGene:19293" and out["ENSEMBL:B"] is None


def test_nameres_lookup_restricts_to_ncbigene_of_the_taxon(monkeypatch):
    seen = []

    def fake(url, payload=None, **kw):
        seen.append(url)
        return [{"curie": "NCBIGene:19293", "label": "Pvalb", "taxa": ["NCBITaxon:10090"]}]

    monkeypatch.setattr(translator, "_http_json", fake)
    out = translator.nameres_lookup("PV", "NCBITaxon:10090")
    assert "only_prefixes=NCBIGene" in seen[0] and "only_taxa=NCBITaxon%3A10090" in seen[0]
    assert out == [{"ncbi_gene_id": "NCBIGene:19293", "label": "Pvalb",
                    "taxa": ["NCBITaxon:10090"]}]


def _fake_nameres(monkeypatch, cands, syns):
    monkeypatch.setattr(translator, "nameres_lookup", lambda name, taxon, **kw: cands)
    monkeypatch.setattr(translator, "nameres_synonyms", lambda ids, **kw: syns)


def test_resolve_by_taxon_counts_exact_name_claimants(monkeypatch):
    _fake_nameres(monkeypatch, [
        {"ncbi_gene_id": "NCBIGene:25248", "label": "Cnr1", "taxa": []},
        {"ncbi_gene_id": "NCBIGene:83839", "label": "Calb1", "taxa": []},
        {"ncbi_gene_id": "NCBIGene:64529", "label": "Ctsb", "taxa": []},
    ], {
        "NCBIGene:25248": ["CB1", "cannabinoid receptor 1"],
        "NCBIGene:83839": ["CB", "calbindin"],
        "NCBIGene:64529": ["CB", "cathepsin B"],
    })
    out = resolve.resolve_by_taxon(["CB"], "NCBITaxon:10116")[0]
    assert out["method"] == AMBIGUOUS and out["gene"] is None
    assert [c["label"] for c in out["claimants"]] == ["Calb1", "Ctsb"]
    # Name Resolver's ranked candidates come back too, for the curator.
    assert len(out["nameres_candidates"]) == 3


@pytest.mark.parametrize("name, method", [("Pvalb", EXACT_SYMBOL),
                                          ("PVALB", CASE_INSENSITIVE_SYMBOL),
                                          ("PV", UNIQUE_SYNONYM)])
def test_resolve_by_taxon_methods(monkeypatch, name, method):
    _fake_nameres(monkeypatch, [{"ncbi_gene_id": "NCBIGene:19293", "label": "Pvalb", "taxa": []}],
                  {"NCBIGene:19293": ["PV", "parvalbumin"]})
    out = resolve.resolve_by_taxon([name], "NCBITaxon:10090")[0]
    assert out["method"] == method
    assert out["gene"] == {"ncbi_gene_id": "NCBIGene:19293", "label": "Pvalb"}
    assert out["claimants"] == [] and out["nameres_candidates"] == []


def test_resolve_by_taxon_symbol_hit_beats_another_genes_synonym(monkeypatch):
    # SST in a mouse paper: Sst by label, Lmx1a lists `sst`. Same answer as a gene table.
    _fake_nameres(monkeypatch, [
        {"ncbi_gene_id": "NCBIGene:20604", "label": "Sst", "taxa": []},
        {"ncbi_gene_id": "NCBIGene:110648", "label": "Lmx1a", "taxa": []},
    ], {"NCBIGene:20604": ["somatostatin"], "NCBIGene:110648": ["sst", "dreher"]})
    out = resolve.resolve_by_taxon(["SST"], "NCBITaxon:10090")[0]
    assert out["method"] == CASE_INSENSITIVE_SYMBOL
    assert out["gene"] == {"ncbi_gene_id": "NCBIGene:20604", "label": "Sst"}
    assert [c["label"] for c in out["claimants"]] == ["Lmx1a"]


def test_resolve_by_taxon_two_genes_with_the_same_label_stay_ambiguous(monkeypatch):
    _fake_nameres(monkeypatch, [
        {"ncbi_gene_id": "NCBIGene:1", "label": "Abc", "taxa": []},
        {"ncbi_gene_id": "NCBIGene:2", "label": "ABC", "taxa": []},
    ], {"NCBIGene:1": [], "NCBIGene:2": []})
    out = resolve.resolve_by_taxon(["abc"], "NCBITaxon:10090")[0]
    assert out["method"] == AMBIGUOUS and out["gene"] is None


def test_resolve_by_taxon_candidate_that_does_not_carry_the_name_is_no_match(monkeypatch):
    # Name Resolver returns fuzzy hits; none lists "BrdU", so nothing claims it.
    _fake_nameres(monkeypatch, [{"ncbi_gene_id": "NCBIGene:1", "label": "Brd1", "taxa": []}],
                  {"NCBIGene:1": ["Brd1", "bromodomain 1"]})
    out = resolve.resolve_by_taxon(["BrdU"], "NCBITaxon:10090")[0]
    assert out["method"] == NO_MATCH and out["nameres_candidates"][0]["label"] == "Brd1"


# ── build-table ──────────────────────────────────────────────────────────────


def test_choose_stats_symbol():
    # A rename the gene still lists is kept.
    assert table.choose_stats_symbol("Car8", "Ca8", ["Car8", "CA-VIII"]) == "Car8"
    # A prior symbol the gene doesn't go by is a mapping error: label wins.
    assert table.choose_stats_symbol("Np65", "Ncam1", ["NCAM", "CD56"]) == "Ncam1"
    assert table.choose_stats_symbol(None, "Ncam1", []) == "Ncam1"
    assert table.choose_stats_symbol("Gm1992", None, []) == "Gm1992"


def test_build_strips_versions_and_keeps_prior_symbols(tmp_path, monkeypatch):
    seen: list[list[str]] = []

    def fake_nodenorm(curies, **kw):
        seen.append(curies)
        return {"ENSEMBL:ENSMUSG00000005716": translator._ncbi_from_nodenorm(_NODENORM_PVALB),
                "ENSEMBL:ENSMUSG00000099999": None}

    monkeypatch.setattr(translator, "nodenorm", fake_nodenorm)
    monkeypatch.setattr(translator, "nameres_synonyms",
                        lambda ids, **kw: {"NCBIGene:19293": ["PV", "Pva"]})
    monkeypatch.setattr(translator, "translator_versions", lambda: {"nodenorm_babel_version": "x"})
    ids = tmp_path / "ids.txt"
    ids.write_text("# header\nENSMUSG00000005716.5\tPva\n\nENSMUSG00000099999\n")
    out = tmp_path / "gene_ids.tsv.gz"
    assert cli.main(["build-table", "--ensembl-ids", str(ids), "-o", str(out), "--label", "T"]) == 0

    assert seen == [["ENSEMBL:ENSMUSG00000005716", "ENSEMBL:ENSMUSG00000099999"]]
    meta, rows = read_gene_ids(out)
    assert meta["dataset_id"] == "T" and meta["n_ncbi"] == "1"
    assert meta["nodenorm_babel_version"] == "x"
    assert rows[0]["stats_symbol"] == "Pva"  # a recorded name: kept
    assert rows[0]["synonyms"] == ["PV", "Pva"]
    assert rows[1] == {
        "ensembl_id": "ENSMUSG00000099999", "stats_symbol": "ENSMUSG00000099999",
        "stats_col": 1, "ncbi_gene_id": None, "label": None, "taxon": None,
        "equivalent_ids": [], "synonyms": [],
    }
    with gzip.open(out, "rt") as fh:
        assert fh.readline() == "#dataset_id\tT\n"


# ── CLI ──────────────────────────────────────────────────────────────────────


def test_cli_resolve_with_table_prints_json(gene_table, capsys):
    assert cli.main(["resolve", "--gene-table", str(gene_table), "PV", "CB"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert [o["method"] for o in out] == [UNIQUE_SYNONYM, AMBIGUOUS]


def test_cli_missing_table_exits_1(tmp_path, capsys):
    assert cli.main(["resolve", "--gene-table", str(tmp_path / "x.tsv.gz"), "PV"]) == 1
    assert "No gene table" in capsys.readouterr().err


def test_cli_corrupt_table_is_not_blamed_on_the_network(tmp_path, capsys):
    bad = tmp_path / "t.tsv.gz"
    bad.write_text("garbage")
    assert cli.main(["resolve", "--gene-table", str(bad), "PV"]) == 1
    err = capsys.readouterr().err
    assert "Cannot read the gene table" in err and "unreachable" not in err


def test_cli_missing_ensembl_id_file_is_not_blamed_on_the_network(tmp_path, capsys):
    assert cli.main(["build-table", "--ensembl-ids", str(tmp_path / "none.txt"),
                     "-o", str(tmp_path / "o.tsv.gz")]) == 1
    err = capsys.readouterr().err
    assert "Cannot read" in err and "unreachable" not in err


def test_cli_network_failure_exits_1_and_warns_against_memory(monkeypatch, capsys):
    def down(*a, **kw):
        raise TimeoutError("timed out")

    monkeypatch.setattr(translator, "nameres_lookup", down)
    assert cli.main(["resolve", "--taxon", "NCBITaxon:10090", "PV"]) == 1
    assert "do not fill in IDs from memory" in capsys.readouterr().err


@pytest.mark.parametrize("taxon", ["10090", "mouse", "NCBITaxon:mouse"])
def test_cli_rejects_a_taxon_that_is_not_a_curie(taxon):
    with pytest.raises(SystemExit) as exc:
        cli.main(["resolve", "--taxon", taxon, "PV"])
    assert exc.value.code == 2


def test_cli_version(capsys):
    with pytest.raises(SystemExit):
        cli.main(["--version"])
    from gene_identity import __version__
    assert capsys.readouterr().out.strip() == f"gene-identity {__version__}"


# ── Live (deselected by default) ─────────────────────────────────────────────


@pytest.mark.live
def test_live_nodenorm_pvalb():
    out = translator.nodenorm(["NCBIGene:19293"], timeout=30, retries=1)
    assert out["NCBIGene:19293"]["label"] == "Pvalb"
    assert out["NCBIGene:19293"]["taxon"] == "NCBITaxon:10090"


@pytest.mark.live
def test_live_resolve_pv_in_mouse():
    out = resolve.resolve_by_taxon(["PV"], "NCBITaxon:10090")[0]
    assert out["gene"] and out["gene"]["label"] == "Pvalb"
