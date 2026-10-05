"""Where a store keeps things, and how a record gets on and off disk.

A store is a directory of paper directories. Paths inside a record are relative
to the record, so a store can be moved, copied or shared without rewriting it.

Nothing here knows about any particular project's layout: the root is always an
argument.
"""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path

from .errors import PaperAccessError
from .ids import Identifier, IdKind, parse_id, slug
from .record import Availability, cross_check, upgraded, validate

logger = logging.getLogger(__name__)

RECORD_NAME = "availability.json"
SOURCE_DIR = "source"
JATS_NAME = "paper.jats.xml"
PDF_NAME = "paper.pdf"
TEXT_NAME = "paper.txt"


def paper_dir(store: str | Path, kind: IdKind, value: str) -> Path:
    """The directory holding one paper's source, text and record."""
    return Path(store) / slug(kind, value)


def _dir_for(store: str | Path, record: Availability) -> Path:
    kind, value = record.primary_id
    return paper_dir(store, kind, value)  # type: ignore[arg-type]


def record_path(store: str | Path, kind: IdKind, value: str) -> Path:
    return paper_dir(store, kind, value) / RECORD_NAME


def read(store: str | Path, identifier: str) -> Availability | None:
    """The record for this paper, or ``None`` where none has been written.

    An identifier that is not the one the paper is filed under still finds it:
    a paper fetched by DOI and later asked for by PMCID is the same paper, and
    a store that answered "no such paper" would fetch it twice.
    """
    kind, value = parse_id(identifier)
    direct = record_path(store, kind, value)
    if direct.is_file():
        return _load(direct)
    for path in sorted(Path(store).glob(f"*/{RECORD_NAME}")) if Path(store).is_dir() else []:
        found = _load(path)
        carried = found.ids.get(kind)
        if carried is not None and carried.value == value:
            return found
    return None


def _load(path: Path) -> Availability:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PaperAccessError(f"cannot read {path}: {exc}") from exc
    return Availability.from_dict(payload)


def read_all(store: str | Path) -> list[Availability]:
    """Every record in a store, in directory order."""
    root = Path(store)
    if not root.is_dir():
        return []
    return [_load(path) for path in sorted(root.glob(f"*/{RECORD_NAME}"))]


def write(store: str | Path, record: Availability) -> Path:
    """Write a record, having validated it first.

    Validation runs before the write, so a record that does not conform is
    never left on disk for a later step to trust.

    Raises:
        PaperAccessError: The record does not conform, or is not self-consistent.
    """
    payload = upgraded(record.to_dict())
    validate(payload)
    problems = cross_check(payload)
    if problems:
        raise PaperAccessError(
            "record is not self-consistent: " + "; ".join(problems)
        )
    directory = _dir_for(store, record)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / RECORD_NAME
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def write_or_note(store_root: str | Path, record: Availability) -> tuple[Path | None, str]:
    """Write a record, and where it will not validate, write it anyway with the
    problems recorded instead of raising.

    An inconsistent record is a bug, and raising is right for a caller that can
    fix it. It is wrong for a corpus sweep: one zero-byte GIF made a paper
    unwritable, and because every later run died at the same write, the paper
    could not be re-attempted and the sweep could not get past it. A paper that
    will not validate has to end up on disk *saying so*, or it blocks
    everything behind it forever.

    Returns:
        Where it was written and an empty note, or ``None`` and why not.
    """
    try:
        return write(store_root, record), ""
    except PaperAccessError as exc:
        logger.error("%s: %s", record.input, exc)
        problem = str(exc)
    note = f"this record did not validate when it was written: {problem}"
    record.notes = f"{record.notes}; {note}" if record.notes else note
    try:
        # Second attempt: the note may be all that was wrong, but if the record
        # is still inconsistent the stripped form below is what lands.
        return write(store_root, record), note
    except PaperAccessError:
        pass
    directory = _dir_for(store_root, record)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / RECORD_NAME
    payload = upgraded(record.to_dict())
    payload["notes"] = note
    payload.pop("supplements", None)
    try:
        validate(payload)
    except PaperAccessError:
        return None, note
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path, note


def store_bytes(
    store: str | Path, record: Availability, kind: str, body: bytes
) -> Path:
    """Put a source file in a paper's directory and return where it went."""
    directory = _dir_for(store, record) / SOURCE_DIR
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / (JATS_NAME if kind == "jats" else PDF_NAME)
    target.write_bytes(body)
    return target


def store_text(store: str | Path, record: Availability, text: str) -> Path:
    directory = _dir_for(store, record) / SOURCE_DIR
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / TEXT_NAME
    target.write_text(text, encoding="utf-8")
    return target


def source_path(store: str | Path, record: Availability) -> Path | None:
    """The stored source file, if this record has one."""
    if record.local_source is None:
        return None
    return _dir_for(store, record) / record.local_source.path


def digest(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def intact(store: str | Path, record: Availability) -> bool:
    """Whether the stored bytes are still there and still what the record says.

    A digest mismatch means the file changed underneath the record. That is not
    an error — someone may have replaced a bad PDF deliberately — but it does
    mean the record no longer describes the file, so the paper is re-fetched
    rather than trusted.
    """
    path = source_path(store, record)
    if path is None or not path.is_file():
        return False
    expected = record.local_source.sha256 if record.local_source else None
    if expected and digest(path.read_bytes()) != expected:
        logger.info("%s: stored source no longer matches its digest", path)
        return False
    return True


def add_id(record: Availability, kind: str, identifier: Identifier) -> None:
    """Record an identifier, keeping the better-attested one on a clash.

    A confirmed identifier never loses to an unconfirmed one, and a value the
    caller supplied never loses to one an API returned: the caller is looking at
    the paper and the API is guessing from a query.
    """
    existing = record.ids.get(kind)
    if existing is None:
        record.ids[kind] = identifier
        return
    if existing.confirmed and not identifier.confirmed:
        return
    if existing.source == "input" and identifier.source != "input":
        return
    record.ids[kind] = identifier
