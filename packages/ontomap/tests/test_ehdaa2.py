"""The staging chain, against the real vendored EHDAA2 and HsapDv tables."""

from conftest import FakeUbergraph
from ontomap import ehdaa2

GRAPH = FakeUbergraph(
    xrefs={
        "UBERON:0002107": ["EHDAA2:0000997"],       # liver
        "UBERON:0004161": ["EHDAA2:0001829"],       # septum transversum
        "UBERON:0002097": ["EHDAA2:0001844"],       # skin
    }
)


def test_the_chain_reaches_days_from_a_uberon_term():
    window = ehdaa2.windows(["UBERON:0002107"], GRAPH)["UBERON:0002107"][0]
    assert window.ehdaa2_id == "EHDAA2:0000997"
    assert window.starts_at_label == "Carnegie stage 12"
    assert window.start_dpf == 26.0


def test_a_lower_bound_refutes_a_too_early_sample():
    window = ehdaa2.windows(["UBERON:0002107"], GRAPH)["UBERON:0002107"][0]
    assert window.covers(20) is False      # liver does not exist yet
    assert window.covers(30) is True


def test_a_closed_window_refutes_a_too_late_sample():
    window = ehdaa2.windows(["UBERON:0004161"], GRAPH)["UBERON:0004161"][0]
    assert window.covers(200) is False
    assert window.covers(20) is True


def test_an_open_window_says_it_cannot_say():
    """Absence of a bound is absence of evidence, not evidence of absence.

    EHDAA2 closes only 1,058 of its 2,444 staged terms. Reading an open end as
    a refutation would replace correct mature terms with precursors wholesale.
    """
    from ontomap.ehdaa2 import Window

    open_window = Window("UBERON:x", "EHDAA2:x", "x", None, None, None, None, None, None)
    assert open_window.covers(30) is None


def test_the_vendored_table_is_the_frozen_release():
    assert ehdaa2.data_version() == "releases/2024-01-11"
