"""ASTA snippet-index depth probe.

Answers one question: *how much of this paper does ASTA's snippet index
actually hold?* Semantic Scholar's metadata graph and the snippet index are
separate systems, and being in one says nothing about being in the other.

The worked example is Yao et al. 2023, "A high-resolution transcriptomic and
spatial atlas of cell types in the whole mouse brain" (``10.1038/s41586-023-
06812-z``, ``CorpusId:266222435``). It is open access, sits in PMC, and its
graph entry carries 118 references — every surface signal says the paper is
available. ASTA's snippet index holds three chunks: title and abstract. No body
text, no section names, no inline reference mentions. Nothing short of probing
tells it apart from a fully indexed paper, and an answer built on it rests on
the abstract alone.

There is no API field that reports snippet coverage. Probing is the only
instrument, which is why it runs for every paper regardless of how the paper
itself arrived.

The bands, and what each one supports:

===============  =================  ===========================================
band             quotable snippets  what it means for a corpus
===============  =================  ===========================================
``full``         yes                may be served from ASTA; reference mentions
                                    are positioned
``partial``      thin               body text present but below the full-text
                                    floor; get the paper another way
``abstract_only``no                 title and abstract; citation edges may exist
                                    via the graph API but carry no offsets
``unindexed``    no                 in Semantic Scholar, absent from the index
``not_in_s2``    no                 no Semantic Scholar record at all
``skipped``      unknown            the probe could not run — nothing was learnt
===============  =================  ===========================================

``skipped`` is not a band, and reporting it beside ``unindexed`` as though the
two were the same finding is the mistake this module is most often used to
avoid.

Calibration
-----------
Measured over 21 papers from a real atlas corpus, at ``limit 100`` per paper.
Three bands separated with no overlap:

===============  ========  ================  ========  ============  ===
band             snippets  chars             sections  refMentions   n
===============  ========  ================  ========  ============  ===
``unindexed``    0         0                 0         0             6
``abstract_only``2..4      1,219..6,312      0         0             3
``full``         15..72    18,802..105,876   9..30     50..361       12
===============  ========  ================  ========  ============  ===

Distinct section names and refMention counts are the two decisive signals and
they are orthogonal: body chunks carry section names, and only a body carries a
bibliography. The gaps are wide (0 vs >=9 sections; 0 vs >=50 refMentions), so
the thresholds below are not finely tuned and should not be treated as though
they were.
"""

from __future__ import annotations

import logging
import os
from typing import Any

import httpx

from .errors import PaperAccessError
from .ids import now
from .record import AstaIndexing

logger = logging.getLogger(__name__)

#: The snippet-search endpoint. One call, one purpose — this is why the package
#: does not depend on a research framework to reach ASTA.
ASTA_SNIPPET_URL = "https://api.semanticscholar.org/graph/v1/snippet/search"

API_KEY_ENV = "ASTA_API_KEY"

MIN_SECTIONS = 1  # >=1 distinct section name means body text is indexed
PARTIAL_SNIPPETS = 10  # below the observed full floor of 15
PARTIAL_CHARS = 15_000  # below the observed full floor of 18,802

#: The probe query is arbitrary: a paper-scoped search returns that paper's
#: whole indexed chunk set, so the query affects the order of the rows and
#: never their number.
PROBE_QUERY = "cell types methods results discussion"

#: Only needs to exceed the largest observed chunk count (72).
PROBE_LIMIT = 100

#: Phrases in an ASTA error that mean "no such paper" rather than "the call
#: failed". A missing paper comes back as a generic error payload with no
#: distinguishable code, so the message is the only signal — hence phrases
#: rather than a substring like "404", which would also match a fault
#: mentioning a paper id such as ``CorpusId:1404567``.
_MISSING_PAPER_PHRASES = (
    "no papers matching",
    "no such paper",
    "paper not found",
    "does not exist",
)


def api_key(explicit: str | None = None) -> str | None:
    """The ASTA key, from the argument or the environment."""
    return explicit or os.getenv(API_KEY_ENV) or None


def count_signals(rows: list[dict[str, Any]]) -> tuple[int, set[str], int, str | None]:
    """Extract (chars, distinct sections, refMention count, corpus id) from rows.

    ``refMentions`` live at ``snippet.annotations.refMentions`` and the key may
    be absent or explicitly null. Section names are null for title and abstract
    pseudo-chunks, which is precisely the signal separating a body from an
    abstract — so only non-null names are counted.
    """
    chars = 0
    sections: set[str] = set()
    ref_mentions = 0
    corpus_id: str | None = None
    for row in rows:
        snippet = row.get("snippet") or {}
        paper = row.get("paper") or {}
        chars += len(snippet.get("text") or "")
        section = snippet.get("section")
        if section:
            sections.add(section)
        annotations = snippet.get("annotations") or {}
        ref_mentions += len(annotations.get("refMentions") or [])
        if corpus_id is None:
            raw = paper.get("corpusId") or paper.get("corpus_id")
            if raw:
                corpus_id = f"CorpusId:{raw}" if str(raw).isdigit() else str(raw)
    return chars, sections, ref_mentions, corpus_id


def classify_rows(rows: list[dict[str, Any]], *, limit: int = PROBE_LIMIT) -> AstaIndexing:
    """Classify a paper's band from its raw snippet-search rows.

    Pure: no I/O. This is the whole decision, and the tests pin it at each
    boundary of the calibration table above.
    """
    chars, sections, ref_mentions, corpus_id = count_signals(rows)
    count = len(rows)

    if count == 0:
        band = "unindexed"
        reason = "0 snippets — ASTA holds nothing for this paper"
    elif len(sections) < MIN_SECTIONS and ref_mentions == 0:
        band = "abstract_only"
        reason = (
            f"{count} snippets, no section names, no refMentions — "
            "title/abstract only, no body text"
        )
    elif count < PARTIAL_SNIPPETS or chars < PARTIAL_CHARS or ref_mentions == 0:
        band = "partial"
        reason = (
            f"{count} snippets / {chars:,} chars / {ref_mentions} refMentions — "
            "below the observed full-text floor"
        )
    else:
        band = "full"
        reason = f"{count} snippets across {len(sections)} sections"

    return AstaIndexing(
        band=band,
        probed_at=now(),
        corpus_id=corpus_id,
        n_snippets=count,
        n_chars=chars,
        n_sections=len(sections),
        n_ref_mentions=ref_mentions,
        limit=limit,
        reason=reason,
    )


def _is_missing_paper(message: str) -> bool:
    low = message.lower()
    return any(phrase in low for phrase in _MISSING_PAPER_PHRASES)


def search_snippets(
    paper_id: str,
    *,
    client: httpx.Client,
    key: str,
    query: str = PROBE_QUERY,
    limit: int = PROBE_LIMIT,
) -> list[dict[str, Any]]:
    """One paper-scoped snippet search, returning the raw rows.

    Raises:
        PaperAccessError: The call failed for a reason other than the paper
            being absent, which is reported as an empty result by the caller.
    """
    response = client.get(
        ASTA_SNIPPET_URL,
        params={"query": query, "limit": limit, "paperIds": paper_id},
        headers={"x-api-key": key},
        timeout=180,
    )
    if response.status_code == 404:
        raise PaperAccessError(f"no such paper: {paper_id}")
    if response.status_code != 200:
        raise PaperAccessError(
            f"snippet search returned {response.status_code}: {response.text[:300]}"
        )
    payload = response.json()
    if isinstance(payload, dict) and payload.get("error"):
        raise PaperAccessError(str(payload["error"]))
    data = payload.get("data") if isinstance(payload, dict) else None
    return list(data or [])


def probe(
    paper_id: str,
    *,
    client: httpx.Client | None = None,
    key: str | None = None,
    limit: int = PROBE_LIMIT,
) -> AstaIndexing:
    """Measure how much of one paper ASTA holds.

    Never raises for an ordinary outcome. A missing key, an unreachable service
    and a paper Semantic Scholar has never heard of are all *results* — recorded
    as ``skipped``, ``skipped`` and ``not_in_s2`` respectively — because a probe
    that raises would take down a waterfall that has other rungs to try.

    Args:
        paper_id: A DOI, ``PMID:…``, ``PMCID:…`` or ``CorpusId:…``, in whatever
            form ASTA accepts; passed through unchanged.
        client: An open HTTP client. One is made and closed if not given.
        key: The ASTA API key. Falls back to ``ASTA_API_KEY``.
        limit: Snippets to ask for. Counts are not comparable across limits.
    """
    resolved = api_key(key)
    if not resolved:
        return AstaIndexing(
            band="skipped",
            probed_at=now(),
            limit=limit,
            reason=(
                f"no {API_KEY_ENV} in the environment, so coverage was not measured; "
                "this is not the same as the paper being unindexed"
            ),
        )

    owned = client is None
    active = client or httpx.Client(timeout=180, follow_redirects=True)
    try:
        rows = search_snippets(paper_id, client=active, key=resolved, limit=limit)
    except PaperAccessError as exc:
        if _is_missing_paper(str(exc)) or "no such paper" in str(exc).lower():
            return AstaIndexing(
                band="not_in_s2",
                probed_at=now(),
                limit=limit,
                reason=f"Semantic Scholar has no record of {paper_id}: {exc}",
            )
        logger.info("ASTA probe failed for %s: %s", paper_id, exc)
        return AstaIndexing(
            band="skipped",
            probed_at=now(),
            limit=limit,
            reason=f"the probe could not run: {exc}",
        )
    except httpx.HTTPError as exc:
        logger.info("ASTA probe unreachable for %s: %s", paper_id, exc)
        return AstaIndexing(
            band="skipped",
            probed_at=now(),
            limit=limit,
            reason=f"the probe could not run: {exc}",
        )
    finally:
        if owned:
            active.close()

    return classify_rows(rows, limit=limit)
