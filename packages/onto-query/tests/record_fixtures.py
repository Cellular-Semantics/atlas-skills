"""Re-record the fixtures the unit suite replays.

    python tests/record_fixtures.py

Run this deliberately, then read the diff. A change in a fixture means the
underlying ontology or API changed, which is information, not noise.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from cassette import FIXTURES, RecordingTransport

from onto_query.ols import (
    hierarchy,
    lexical,
    linked_entities,
    neighbours,
    search_config,
)
from onto_query.releases import ols4_release, ubergraph_release
from onto_query.transport import Transport
from onto_query.ubergraph import Ubergraph

# One case per behaviour the unit suite asserts. Small on purpose: these are
# contract tests, not a corpus.
OLS_CASES = [
    ("skin", "uberon", ("exact",)),
    ("muscle", "uberon", ("exact",)),
    ("full reproductive tract", "uberon", ("exact",)),
    ("thoracic spine", "uberon", ("exact",)),
    ("skin", "uberon", ("exact", "stemmed")),
]

CA_CASES = [
    (["UBERON:0000964", "UBERON:0001811"], "uberon", ("subClassOf", "part_of")),
    (["UBERON:0000964", "UBERON:0001811"], "uberon", ("subClassOf",)),
    (["GO:0006096", "GO:0006099"], "go", ("subClassOf", "part_of")),
    (["CL:0000604", "CL:0000573", "CL:0000636"], "uberon", ("subClassOf", "part_of")),
]


def main() -> int:
    for stale in FIXTURES.glob("*.json"):
        stale.unlink()
    rec = RecordingTransport(Transport())

    search_config(rec, "uberon")
    search_config(rec, "efo")  # declares its own synonym properties
    search_config(rec, "ehdaa2")  # declares no preferred prefix
    lexical(rec, "liver", "ehdaa2", probes=("exact",))
    for query, ontology, probes in OLS_CASES:
        lexical(rec, query, ontology, probes=probes)
    # a deliberately capped call, so truncation can be tested offline
    lexical(rec, "skin", "uberon", probes=("stemmed",), rows=10)

    ug = Ubergraph(rec)
    ug.named_graphs()
    for seeds, target, preds in CA_CASES:
        ug.common_ancestors(seeds, target, preds)
    ug.relations("UBERON:0000966", "part_of", "in", target_ontology="cl")
    ug.cohort("hsapdv", label_contains="week")
    ug.xrefs("UBERON:0010409")
    ug.xrefs("MONDO:0007739")
    ug.crosswalk("EHDAA2:0000997", "uberon")
    ug.crosswalk("EMAPA:16846")
    ug.crosswalk("NOSUCH:9999999", "uberon")
    neighbours(rec, "ehdaa2", "EHDAA2:0000997")
    hierarchy(rec, "ehdaa2", "EHDAA2:0000997", "up")
    hierarchy(rec, "ehdaa2", "EHDAA2:0000997", "down")
    linked_entities(rec, "uberon", "UBERON:0010409")

    # release checks: one resident ontology, one OLS4-only ontology
    for ont in ("hsapdv", "ehdaa2"):
        ols4_release(rec, ont)
        ubergraph_release(ug, ont)

    print(f"wrote {len(rec.written)} fixtures to {FIXTURES}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
