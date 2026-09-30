"""Recovering text from a PDF, with an honest account of what came out.

A PDF is the worst of the sources this package handles and the account matters
more than the text. Two things are lost and neither is recoverable later:

* **Reference markup.** No citation can be resolved from recovered text, so
  nothing can walk the paper's bibliography.
* **Reading order across a column boundary.** Each paragraph is internally
  coherent, but a quote spanning a boundary may correspond to nothing a reader
  of the article would ever see.

A third thing is not lost but must be visible: a PDF of page images extracts to
almost nothing, and "almost nothing" is indistinguishable from a short paper
unless the size is on the record.

Figure-internal text — axis labels, panel tags, gene-name strips — is dropped.
It is not quotable prose and it inflates every size measure it appears in.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .errors import PaperAccessError

#: Below this, recovered text is not worth reading. Deliberately blunt: it
#: catches the case it exists for, a PDF of page images, and leaves the finer
#: judgement — whether the reading order survived — to a reader who can see the
#: text.
MIN_READABLE_CHARS = 4_000

#: pymupdf4llm brackets figure-internal text with these markers.
_FIGURE_START = re.compile(r"^\s*(?:<!--\s*)?Start of picture text", re.IGNORECASE)
_FIGURE_END = re.compile(r"^\s*(?:<!--\s*)?End of picture text", re.IGNORECASE)
_HEADING = re.compile(r"^\s{0,3}(#{1,6})\s+(.*\S)\s*$")


@dataclass
class Segment:
    """One paragraph, and the section heading it sits under."""

    section: str
    text: str


def _to_markdown(pdf_path: str | Path) -> str:
    try:
        import pymupdf4llm
    except ImportError as exc:  # pragma: no cover - environment guard
        raise PaperAccessError(
            "reading a PDF needs the [text-access] extra (pymupdf4llm): "
            "pip install 'paper-access[text-access]'"
        ) from exc
    return str(pymupdf4llm.to_markdown(str(pdf_path)))


def segments_from_markdown(markdown: str) -> list[Segment]:
    """Split extracted markdown into paragraph segments under their headings.

    Pure, so the splitting is testable without a PDF — which matters, because
    the shape of what comes back from the extractor is most of what can go
    wrong here.
    """
    out: list[Segment] = []
    section = "BODY"
    in_figure = False
    buffer: list[str] = []

    def flush() -> None:
        text = " ".join(" ".join(buffer).split()).strip()
        buffer.clear()
        if text:
            out.append(Segment(section=section, text=text))

    for line in markdown.splitlines():
        if _FIGURE_START.match(line):
            flush()
            in_figure = True
            continue
        if _FIGURE_END.match(line):
            flush()
            in_figure = False
            continue
        if in_figure:
            continue
        heading = _HEADING.match(line)
        if heading:
            flush()
            section = heading.group(2).strip()
            continue
        if not line.strip():
            flush()
            continue
        buffer.append(line.strip())
    flush()
    return out


def describe(segments: list[Segment], text: str) -> dict[str, Any]:
    """Size and shape of recovered text, for judging whether to read it."""
    quality: dict[str, Any] = {"n_segments": len(segments), "n_chars": len(text)}
    if segments:
        quality["mean_chars_per_segment"] = round(
            sum(len(s.text) for s in segments) / len(segments), 1
        )
    sample = "\n\n".join(s.text for s in segments[:3])[:600]
    if sample:
        quality["sample"] = sample
    return quality


def extract(pdf_path: str | Path) -> tuple[str, dict[str, Any]]:
    """Recover text from a PDF, and say how much came out.

    Returns:
        The text, and its size and shape. A scan yields a handful of very short
        segments, which is what the shape is for.

    Raises:
        PaperAccessError: The extractor is not installed, or the file cannot be
            read as a PDF.
    """
    markdown = _to_markdown(pdf_path)
    segments = segments_from_markdown(markdown)

    parts: list[str] = []
    current: str | None = None
    for segment in segments:
        if segment.section != current:
            if segment.section and segment.section != "BODY":
                parts.append(f"\n## {segment.section}\n")
            current = segment.section
        parts.append(segment.text)
    text = "\n".join(parts).strip()
    return text, describe(segments, text)


def looks_readable(quality: dict[str, Any]) -> bool:
    """Whether recovered text is worth reading at all."""
    return int(quality.get("n_chars", 0)) >= MIN_READABLE_CHARS
