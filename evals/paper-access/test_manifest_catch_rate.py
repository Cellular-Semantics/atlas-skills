"""The supplement manifest check's catch rate, pinned. Offline and free.

See manifest_catch_rate.py for what the mutations are and what the rate means.
"""
import pytest

pytest.importorskip("paper_access")

from manifest_catch_rate import MUTATIONS, NOT_CATCHABLE, measure


@pytest.fixture(scope="module")
def result():
    return measure()


def test_the_clean_store_passes(result):
    """A check that blocks a good manifest gets switched off."""
    assert result["unmutated"]["problems"] == []


@pytest.mark.parametrize("name", sorted(set(MUTATIONS) - NOT_CATCHABLE))
def test_every_catchable_mutation_is_caught_every_time(result, name):
    m = result["mutations"][name]
    assert m["applied"] >= 1, "the mutation never applied"
    assert m["caught"] == m["applied"]


def test_swapped_captions_are_beyond_the_check(result):
    """The check sees structure, not meaning. If this starts catching, it is
    rejecting real descriptions and the clean-store test should be failing too."""
    m = result["mutations"]["caption_swapped"]
    assert m["applied"] == 1
    assert m["caught"] == 0
