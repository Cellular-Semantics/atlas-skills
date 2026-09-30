"""Splitting extracted PDF markdown, and describing what came out.

The splitting is pure, so it is tested without a PDF — which is the point:
what goes wrong here is the *shape* of what the extractor returns, not PyMuPDF.
"""

from __future__ import annotations

from paper_access.pdftext import (
    MIN_READABLE_CHARS,
    Segment,
    describe,
    looks_readable,
    segments_from_markdown,
)

MARKDOWN = """\
# Results

We identified 5,322 clusters in the mouse brain. The clusters were annotated
using a combination of markers.

Start of picture text
Fig 1a
UMAP-1
UMAP-2
End of picture text

## Cell type annotation

Clusters were named by their markers.
"""


def test_headings_become_sections():
    segments = segments_from_markdown(MARKDOWN)
    assert [s.section for s in segments] == ["Results", "Cell type annotation"]


def test_a_paragraph_is_reflowed_onto_one_line():
    first = segments_from_markdown(MARKDOWN)[0]
    assert "\n" not in first.text
    assert first.text.startswith("We identified 5,322 clusters")


def test_figure_internal_text_is_dropped():
    """Axis labels and panel tags are not quotable prose, and they inflate
    every size measure they appear in."""
    text = " ".join(s.text for s in segments_from_markdown(MARKDOWN))
    assert "UMAP-1" not in text
    assert "Fig 1a" not in text


def test_text_after_a_figure_block_is_kept():
    sections = [s.section for s in segments_from_markdown(MARKDOWN)]
    assert "Cell type annotation" in sections


def test_markdown_with_no_headings_still_yields_paragraphs():
    segments = segments_from_markdown("One paragraph.\n\nAnother one.\n")
    assert [s.section for s in segments] == ["BODY", "BODY"]
    assert len(segments) == 2


def test_empty_input_yields_nothing():
    assert segments_from_markdown("") == []
    assert segments_from_markdown("\n\n   \n") == []


# -- the account of what came out ---------------------------------------


def test_describe_carries_the_opening_so_a_reader_can_see_sentences():
    segments = [Segment("BODY", "A real sentence about cell types.")]
    quality = describe(segments, "A real sentence about cell types.")
    assert quality["n_segments"] == 1
    assert quality["n_chars"] == 33
    assert "A real sentence" in quality["sample"]


def test_a_scan_is_a_handful_of_very_short_segments():
    """What the shape exists to separate from a short paper."""
    segments = [Segment("BODY", "1"), Segment("BODY", "2"), Segment("BODY", "3")]
    quality = describe(segments, "1\n2\n3")
    assert quality["mean_chars_per_segment"] == 1.0
    assert not looks_readable(quality)


def test_a_paper_looks_readable():
    assert looks_readable({"n_chars": MIN_READABLE_CHARS})
    assert not looks_readable({"n_chars": MIN_READABLE_CHARS - 1})
    assert not looks_readable({})
