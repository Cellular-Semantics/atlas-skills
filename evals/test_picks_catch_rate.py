"""The picks.json check's catch rate, pinned. Offline and free, so it runs in CI.

See picks_catch_rate.py for what the mutations are and what the rate means.
"""
import pytest
from picks_catch_rate import KNOWN_BAD, MUTATIONS, NOT_CATCHABLE, measure

pytest.importorskip("jsonschema")


@pytest.fixture(scope="module")
def result():
    return measure()


def test_no_frozen_answer_is_falsely_rejected(result):
    """A check that blocks good reports gets switched off."""
    assert result["unmutated"]["false_rejects"] == []


def test_the_known_picker_error_is_caught(result):
    assert result["unmutated"]["known_bad_caught"] == sorted(KNOWN_BAD)


@pytest.mark.parametrize("name", sorted(set(MUTATIONS) - NOT_CATCHABLE))
def test_every_catchable_mutation_is_caught_every_time(result, name):
    m = result["mutations"][name]
    assert m["applied"] >= 40, "too few datasets to say anything"
    assert m["caught"] == m["applied"]


def test_a_wrong_but_real_column_is_beyond_the_check(result):
    """The check sees names, not meaning. If this starts catching, it is
    rejecting real columns and the false-reject test should be failing too."""
    assert result["mutations"]["wrong_but_real"]["caught"] == 0
