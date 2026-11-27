import pytest


@pytest.fixture(autouse=True)
def _isolated_cache(tmp_path, monkeypatch):
    """`resolve` logs every ID it prints and `check` caches lookups: never
    into the developer's own ~/.cache."""
    monkeypatch.setenv("GENE_IDENTITY_CACHE", str(tmp_path / "cache"))
