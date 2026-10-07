#!/usr/bin/env python3
"""Measure what verify-ehdaa2-claims.py actually catches, by breaking the reference.

    uv run evals/ontology-mapping/mutate-ehdaa2-claims.py

Each mutation is one error class a reader could not see for themselves: a window
off by a stage, a swapped digit, a CURIE wearing another term's label. The
verifier is not finished until this reports the catch rate, and a verifier that
scores below 8/8 here has lost coverage it used to have.

The file is restored afterwards whatever happens. Run it after editing either
the reference or the verifier.
"""
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO = next(q for q in Path(__file__).parents if (q / "plugins").is_dir())
DOC = REPO / "docs/archive/ehdaa2-investigation/uberon-developmental.md"
VERIFY = REPO / "docs/archive/ehdaa2-investigation/verify-ehdaa2-claims.py"

# (error class, text to find, what to replace it with)
MUTATIONS = [
    ("existence window off by one stage",
     "`EHDAA2:0001130` mesonephros | CS11 - CS18",
     "`EHDAA2:0001130` mesonephros | CS11 - CS17"),
    ("digit swapped in a CURIE",
     "`EHDAA2:0001137` metanephros",
     "`EHDAA2:0001136` metanephros"),
    ("CURIE paired with another term's label",
     "`EHDAA2:0001570` pronephros",
     "`EHDAA2:0001570` notochord"),
    ("wrong Uberon term in an xref pair",
     "`UBERON:0002120` |",
     "`UBERON:0000084` |"),
    ("count perturbed",
     "224 EHDAA2 classes exist at",
     "226 EHDAA2 classes exist at"),
    ("single-stage window widened",
     "pronephros | CS09 only",
     "pronephros | CS09 - CS12"),
    ("end bound dropped from a table row",
     "mesonephros | CS11 - CS18",
     "mesonephros | CS11 - (no end asserted)"),
    ("navigation answer swapped for an out-of-range term",
     "| `develops_from`, direction `in` | `UBERON:0001891` midbrain |",
     "| `develops_from`, direction `in` | `UBERON:0009616` presumptive midbrain |"),
    ("navigation answer swapped for an unxrefed term",
     "| `part_of`, direction `out` | `UBERON:0005290` myelencephalon |",
     "| `part_of`, direction `out` | `UBERON:0003076` posterior neural tube |"),
    ("a refutation that does not refute",
     "| `spinal cord` at CS12 | `EHDAA2:0001255` starts CS13 |",
     "| `spinal cord` at CS14 | `EHDAA2:0001255` starts CS13 |"),
    ("claimed absence that is not absent",
     "`EHDAA2:0004471 ventral thalamus`, and that one has **no Uberon xref at\nall**",
     "`EHDAA2:0004470 subthalamus`, and that one has **no Uberon xref at\nall**"),
    ("substage count perturbed",
     "**57 classes are anchored to Carnegie substages instead**",
     "**59 classes are anchored to Carnegie substages instead**"),
    ("somite hole count perturbed",
     "39 of\n  the affected 224",
     "41 of\n  the affected 224"),
    ("future-X xref retargeted",
     "`EHDAA2:0000234 future cerebral cortex` (CS16-) xrefs `UBERON:0000956 cerebral",
     "`EHDAA2:0000234 future cerebral cortex` (CS16-) xrefs `UBERON:0000369 cerebral"),
    ("precursor coverage overstated",
     "only **79\n(32%)** carry an EHDAA2 xref",
     "only **91\n(32%)** carry an EHDAA2 xref"),
    ("sweep refutation count drifted",
     "| substring / token overlap | 25 | 2 |",
     "| substring / token overlap | 21 | 2 |"),
    ("CS20 ceiling raised",
     "falls between `HsapDv:0000003` (CS01) and\n`HsapDv:0000027` (**CS20**)",
     "falls between `HsapDv:0000003` (CS01) and\n`HsapDv:0000030` (**CS23**)"),
]


def verify() -> int:
    r = subprocess.run(
        ["uv", "run", str(VERIFY), "--offline", "--skip-ols4"],
        capture_output=True, text=True, cwd=REPO,
    )
    return r.stdout.count("FAIL")


def main() -> int:
    original = DOC.read_text()

    if verify():
        print("baseline is not clean -- fix the reference before measuring")
        DOC.write_text(original)
        return 2

    caught = 0
    try:
        for name, find, replace in MUTATIONS:
            if find not in original:
                print(f"  SKIP     {name}  (anchor no longer in the file)")
                continue
            DOC.write_text(original.replace(find, replace, 1))
            n = verify()
            caught += n > 0
            print(f"  {'CAUGHT' if n else 'MISSED'}   {name}")
    finally:
        DOC.write_text(original)

    print(f"\ncatch rate: {caught}/{len(MUTATIONS)}")
    return 0 if caught == len(MUTATIONS) else 1


if __name__ == "__main__":
    sys.exit(main())
