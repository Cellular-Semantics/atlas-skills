"""Check the identifiers in a written document against a store.

A DOI quoted in a report is an assertion about which paper a claim came from.
A recalled one is wrong in a way no reader can detect, and a reader who tries
to follow it lands on a different paper or on nothing. So before a document
goes anywhere, every identifier in it should be one the store actually holds.

Deliberately one-directional: it complains about identifiers the store does not
know, never about papers the document does not cite. A report that covers a
subset of a corpus is the normal case.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .errors import PaperAccessError
from .ids import find_ids
from .store import read_all


def known_ids(store_root: str | Path) -> dict[str, set[str]]:
    """Every identifier the store holds, by kind.

    Unconfirmed identifiers count as known. A candidate in the store is
    something a person is being asked about, and a document that mentions one
    is describing the question rather than making a claim.
    """
    found: dict[str, set[str]] = {"doi": set(), "pmid": set(), "pmcid": set()}
    for record in read_all(store_root):
        for kind, identifier in record.ids.items():
            found.setdefault(kind, set()).add(identifier.value)
    return found


def check_document(document: str | Path, store_root: str | Path) -> list[dict[str, Any]]:
    """Identifiers in a document that the store does not hold.

    Returns:
        One entry per unknown identifier, with its kind and value. Empty when
        everything checks out.
    """
    path = Path(document)
    if not path.is_file():
        raise PaperAccessError(f"no such file: {path}")
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise PaperAccessError(f"cannot read {path}: {exc}") from exc

    known = known_ids(store_root)
    cited = find_ids(text)

    problems: list[dict[str, Any]] = []
    for kind, values in sorted(cited.items()):
        for value in sorted(values - known.get(kind, set())):
            problems.append({"kind": kind, "value": value})
    return problems


def describe(problems: list[dict[str, Any]], document: str | Path, store_root: str | Path) -> str:
    """The message a hook prints when a document cites something unknown."""
    lines = [
        f"{len(problems)} identifier(s) in {Path(document).name} are not in the "
        f"paper store at {store_root}:",
        "",
    ]
    lines += [f"  {p['kind'].upper()} {p['value']}" for p in problems]
    lines += [
        "",
        "An identifier that is not in the store was not retrieved, which means it "
        "was recalled rather than read. Either fetch the paper —",
        "",
        "  paper-access fetch --store <store> --id <id>",
        "",
        "— or take the citation out. Do not correct it from memory.",
    ]
    return "\n".join(lines)
