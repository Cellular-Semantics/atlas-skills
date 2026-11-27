"""The gene records check's catch rate, pinned. Offline and free.

See record_catch_rate.py for what the mutations are and what the rate means.
"""
import pytest

pytest.importorskip("gene_identity")

from record_catch_rate import (
    CATCHABLE,
    CONTROLS,
    NOT_CATCHABLE,
    PROVENANCE_ONLY,
    measure,
)


@pytest.fixture(scope="module")
def result():
    return measure()


def test_the_clean_file_passes(result):
    """A check that flags good records gets switched off."""
    assert result["unmutated_file"] == {"problems": [], "unchecked": []}


@pytest.mark.parametrize("name", sorted(CATCHABLE))
def test_every_catchable_class_is_always_caught(result, name):
    c = result["classes"][name]
    assert c["tried"] > 0, "the class applies to no record: the measurement measures nothing"
    assert c["caught"] == c["tried"], c


@pytest.mark.parametrize("name", sorted(set(CATCHABLE) - PROVENANCE_ONLY))
def test_each_class_is_caught_by_its_own_check_not_only_the_resolve_log(result, name):
    c = result["classes"][name]
    assert c["caught_without_provenance"] == c["tried"], c


@pytest.mark.parametrize("name", sorted(CONTROLS))
def test_controls_are_never_flagged(result, name):
    c = result["classes"][name]
    assert c["tried"] > 0 and c["caught"] == 0, c


@pytest.mark.parametrize("name", sorted(NOT_CATCHABLE))
def test_the_stated_limit_holds(result, name):
    """The check can't tell a right gene from a wrong one that is real, looked
    up and consistent. If this starts passing, the doc's stated limit is wrong."""
    c = result["classes"][name]
    assert c["tried"] > 0 and c["caught"] == 0, c


def test_nothing_was_left_unchecked(result):
    """The world is complete: an unchecked lookup would hide a miss."""
    assert all(c["unchecked"] == 0 for c in result["classes"].values())
