"""Check a ``picks.json`` report against its schema and against the obs it names.

Each column in a report is a claim that the column exists in obs and holds the
authors' annotation for that field type. The second half of that claim needs
judgement, and the evals measure it. The first half is mechanical, and a
picker that invents, misspells or recases a name fails it in a way that a
summary written for the user would hide. This catches that half.

Three layers, each reported separately so a failure says which one it was:

1. **shape** -- the JSON Schema in ``schemas/picks.schema.json``;
2. **consistency** -- what the schema cannot say: every requested field type
   has a ``picks`` key, and every picker whose field types were requested left
   its reasoning;
3. **existence** -- every picked column is a column of ``source``.

The schema needs ``jsonschema`` and a parquet source needs ``pyarrow``. Both
come from the ``check`` extra, so the base package stays dependency-free.
"""
from __future__ import annotations

import csv
import difflib
import json
from collections.abc import Iterable
from pathlib import Path

from .candidates import column_names as profile_column_names

SCHEMA_PATH = Path(__file__).parent / "schemas" / "picks.schema.json"

#: Which picker answers which field types. A report that asks for a field
#: type must carry the reasoning of the agent that picks it.
PICKER_FOR = {
    "cell_type": "author-celltype-picker",
    "tissue": "author-sample-field-picker",
    "development_stage": "author-sample-field-picker",
    "other_stage": "author-sample-field-picker",
    "disease": "author-sample-field-picker",
}


def load_schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text())


def shape_problems(report: object) -> list[str]:
    """JSON Schema violations, each prefixed with where in the report it is."""
    try:
        from jsonschema import Draft202012Validator
    except ImportError as exc:  # pragma: no cover - the extra is missing
        raise RuntimeError(
            "checking a report needs jsonschema: install obs-column-eval[check]"
        ) from exc
    validator = Draft202012Validator(load_schema())
    out = []
    for err in sorted(validator.iter_errors(report), key=lambda e: list(e.path)):
        where = "/".join(str(p) for p in err.path) or "(top level)"
        out.append(f"{where}: {_readable(err)}")
    return out


def _readable(err) -> str:
    """The schema's message, except where it would show the model a regex.

    The one `not` in the schema is the portal-field ban on a column name, and
    its raw message quotes the pattern rather than saying what is wrong.
    """
    if err.validator == "not" and isinstance(err.instance, str):
        col = err.instance
        if col.endswith("_ontology_term_id"):
            return (f"`{col}` is an ontology term id column, never a pick; "
                    "pick the column holding the authors' labels")
        return (f"`{col}` is the portal's standardised field, never a pick; "
                "pick the authors' own column")
    return err.message


def _usable_picks(report: object) -> dict[str, list[str]]:
    """Whatever column names can be read out of a report, valid or not.

    Used so that a schema failure does not hide a missing column: every
    problem is reported in one pass, not one per fix.
    """
    if not isinstance(report, dict) or not isinstance(report.get("picks"), dict):
        return {}
    return {str(ft): [c for c in cols if isinstance(c, str) and c]
            for ft, cols in report["picks"].items() if isinstance(cols, list)}


def consistency_problems(report: dict) -> list[str]:
    """What the schema cannot express. Assumes the report passed the schema."""
    out = []
    requested = report["requested"]
    picks = report["picks"]
    reasoning = report["reasoning"]
    for ft in requested:
        if ft not in picks:
            out.append(f"picks: `{ft}` was requested and has no key; write "
                       f"`\"{ft}\": []` if the picker found nothing")
    for ft in picks:
        if ft not in requested:
            out.append(f"picks: `{ft}` was not requested; add it to `requested` "
                       f"or drop it")
    for agent in sorted({PICKER_FOR[ft] for ft in requested}):
        if agent not in reasoning:
            out.append(f"reasoning: no entry from `{agent}`, which picks "
                       f"{', '.join(f for f in requested if PICKER_FOR[f] == agent)}")
    return out


def source_columns(source: Path) -> list[str]:
    """The column names of an obs table: parquet, csv/tsv, or a text profile.

    A parquet file is read for its schema only, never its rows. A pandas index
    stored as a column is included; a picker naming it is wrong for other
    reasons, and none of them is that the name does not exist.
    """
    suffix = source.suffix.lower()
    if suffix == ".parquet":
        try:
            import pyarrow.parquet as pq
        except ImportError as exc:
            raise RuntimeError(
                "reading a parquet source needs pyarrow: install "
                "obs-column-eval[check]") from exc
        return list(pq.read_schema(source).names)
    if suffix in {".csv", ".tsv"}:
        with source.open(newline="") as fh:
            header = next(csv.reader(fh, delimiter="\t" if suffix == ".tsv" else ","), [])
        # pandas writes the index first, under an empty name when it has none.
        return [h for h in header if h]
    if suffix == ".txt":
        return profile_column_names(source.read_text())
    raise ValueError(f"cannot read columns from {source.name}: expected .parquet, "
                     ".csv, .tsv or a text profile (.txt)")


def existence_problems(picks: dict[str, list[str]], columns: Iterable[str]) -> list[str]:
    """Every picked column that is not in obs, with the nearest real name."""
    have = list(columns)
    present = set(have)
    out = []
    for ft, cols in picks.items():
        for col in cols:
            if col in present:
                continue
            msg = f"picks/{ft}: `{col}` is not a column of the source obs"
            near = _nearest(col, have)
            if near:
                msg += f"; did you mean `{near}`?"
            out.append(msg)
    return out


def _nearest(name: str, have: list[str]) -> str | None:
    for h in have:
        if h.lower() == name.lower():
            return h
    close = difflib.get_close_matches(name, have, n=1, cutoff=0.8)
    return close[0] if close else None


def check_report(path: Path) -> dict:
    """Check one report. ``{"ok": bool, "problems": [...], ...}``, never raises
    for a problem with the report -- only for one with the checker."""
    result: dict = {"report": str(path), "ok": False, "problems": []}
    try:
        report = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        result["problems"] = [f"not valid JSON: {exc}"]
        return result

    problems = shape_problems(report)
    if not problems:
        # It assumes the report's structure, so only on a report that has it.
        problems = consistency_problems(report)

    # Existence runs whatever the schema said, on every name that can be read:
    # one pass reports every problem, rather than one per round of fixes.
    picks = _usable_picks(report)
    raw_source = report.get("source") if isinstance(report, dict) else None
    if not picks:
        pass  # nothing to look up; the schema has already said why
    elif not isinstance(raw_source, str) or not raw_source:
        problems.append("columns not checked against obs: no usable `source`")
    else:
        source = Path(raw_source)
        if not source.is_absolute():
            source = path.parent / source
        result["source"] = str(source)
        if not source.exists():
            problems.append(f"source: `{raw_source}` does not exist (resolved "
                            f"to {source}), so no picked column can be confirmed")
        else:
            try:
                problems += existence_problems(picks, source_columns(source))
            except ValueError as exc:
                problems.append(f"source: {exc}")

    result["problems"] = problems
    result["ok"] = not problems
    return result
