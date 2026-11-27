"""NLM-Gene (Islamaj et al. 2021) → gene-id-curation cases.

Pure functions: parse BioC XML, turn each gene mention into the skill's input
(``name``, ``taxon``, ``title``, ``evidence``) and the expected record. The
snapshot script supplies what needs a network (current gene IDs and taxa,
the lookup's own answer) as plain dicts.

The mapping, from the released corpus (which, unlike the annotation
guidelines, carries almost none of the ``-000``/``-222`` codes):

| Annotation | Expected |
|---|---|
| one NCBI Gene ID, and the mention is one of that gene's names | ``GENE``, that gene (its current ID if merged) |
| one NCBI Gene ID, but the mention is not one of its names ("Kinases" → AKT1, "GPCR" → Gpr34: the guidelines' pick-a-member convention, its ``-333`` code dropped from the release) | ``GENE`` that gene **or** ``NO_SINGLE_GENE``: marked ``generic`` |
| several IDs, comma-separated (a family or class: "Wnt", "protein kinase") | ``NO_SINGLE_GENE``; ``kind`` not scored (the gold doesn't say family vs complex) |
| several IDs, semicolon-separated (an ellipsis naming genes: "ERK1/2") | excluded: one span, several genes named |
| an ID with a ``-NNN`` code | excluded: too few to score as a class |
| no ID (types ``Other``, ``Domain``) | excluded |
| an ID NodeNorm no longer knows, or genes of more than one species | excluded |

One case per (document, mention text, expected answer): the same mention
repeated in an abstract is one decision.

"One of its names" is decided by :func:`names_gene`: the mention, normalised
as the lookup normalises (case, spaces, hyphens, underscores), equals the
gene's official label or one of its Name Resolver synonyms.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

_NORM = re.compile(r"[\s\-_]+")


def _norm(name: str) -> str:
    return _NORM.sub("", name).lower()


def names_gene(mention: str, label: str | None, synonyms: Iterable[str]) -> bool:
    """Whether the mention is one of the gene's own names."""
    want = _norm(mention)
    return want == _norm(label or "") or any(want == _norm(s) for s in synonyms)


_SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9(\[])")


@dataclass(frozen=True)
class Mention:
    pmid: str
    text: str
    raw_ids: str
    ann_type: str
    passage: str          # "title" or "abstract"
    offset: int           # within the passage text
    passage_text: str


@dataclass(frozen=True)
class Document:
    pmid: str
    title: str
    mentions: tuple[Mention, ...]


def parse_document(xml: bytes | str) -> Document:
    root = ET.fromstring(xml)
    doc = root.find("document")
    if doc is None:
        raise ValueError("no <document> in BioC collection")
    pmid = doc.findtext("id") or ""
    title = ""
    mentions = []
    for p in doc.findall("passage"):
        kind = next((i.text for i in p.findall("infon") if i.get("key") == "type"), "") or ""
        text = p.findtext("text") or ""
        base = int(p.findtext("offset") or 0)
        if kind == "title":
            title = text
        for a in p.findall("annotation"):
            inf = {i.get("key"): (i.text or "") for i in a.findall("infon")}
            loc = a.find("location")
            off = int(loc.get("offset")) - base if loc is not None else -1
            mentions.append(Mention(pmid, a.findtext("text") or "", inf.get("NCBI Gene identifier", ""),
                                    inf.get("type", ""), kind, off, text))
    return Document(pmid, title, tuple(mentions))


def sentence_at(text: str, offset: int) -> str:
    """The sentence of ``text`` containing ``offset``."""
    start = 0
    for m in _SENTENCE_END.finditer(text):
        if m.start() >= offset:
            return text[start:m.start()].strip()
        start = m.end()
    return text[start:].strip()


def classify(raw_ids: str) -> tuple[str, list[str]]:
    """``(shape, ids)``: shape is ``single``, ``family``, or why it's excluded."""
    raw = raw_ids.strip()
    if not raw:
        return "no_id", []
    if re.search(r"-\d{3}", raw):
        return "coded", []
    if ";" in raw:
        return "ellipsis", []
    ids = [i.strip() for i in raw.split(",") if i.strip()]
    if not all(i.isdigit() for i in ids):
        return "malformed", []
    ids = list(dict.fromkeys(ids))
    return ("single" if len(ids) == 1 else "family"), [f"NCBIGene:{i}" for i in ids]


def build_cases(
    docs: Iterable[Document],
    genes: Mapping[str, dict | None],
    names: Mapping[str, list[str]] | None = None,
) -> tuple[list[dict], Counter]:
    """Cases and a count of what was excluded and why.

    ``genes`` is NodeNorm's answer per gold ID: ``{ncbi_gene_id, label,
    taxon}`` (``ncbi_gene_id`` differing from the key means merged into it),
    or None. ``names`` is each current ID's Name Resolver synonyms; a single-ID
    mention that is none of its gene's names is ``generic``. Without
    ``names`` every single-ID mention counts as naming its gene.
    """
    cases: list[dict] = []
    excluded: Counter = Counter()
    seen: set[tuple] = set()
    for doc in docs:
        for m in doc.mentions:
            shape, ids = classify(m.raw_ids)
            if shape not in ("single", "family"):
                excluded[shape] += 1
                continue
            current = [genes.get(i) for i in ids]
            if any(g is None or not g.get("ncbi_gene_id") for g in current):
                excluded["id_not_in_nodenorm"] += 1
                continue
            taxa = {g.get("taxon") for g in current}
            if len(taxa) != 1 or None in taxa:
                excluded["mixed_or_unknown_species"] += 1
                continue
            taxon = taxa.pop()
            if shape == "single":
                g = current[0]
                generic = names is not None and not names_gene(
                    m.text, g["label"], names.get(g["ncbi_gene_id"], []))
                expected = {"outcome": "GENE", "kind": None, "generic": generic,
                            "accept": [{"ncbi_gene_id": g["ncbi_gene_id"], "symbol": g["label"]}]}
            else:
                expected = {"outcome": "NO_SINGLE_GENE", "kind": None, "accept": [],
                            "members": sorted({g["ncbi_gene_id"] for g in current})}
            key = (doc.pmid, m.text, expected["outcome"],
                   tuple(a["ncbi_gene_id"] for a in expected["accept"]) or tuple(expected.get("members", ())))
            if key in seen:
                excluded["repeat_in_document"] += 1
                continue
            seen.add(key)
            remapped = {i: g["ncbi_gene_id"] for i, g in zip(ids, current, strict=True)
                        if g["ncbi_gene_id"] != i}
            cases.append({
                "id": f"nlm-{doc.pmid}-{len([c for c in cases if c['pmid'] == doc.pmid]) + 1:02d}",
                "pmid": doc.pmid,
                "input": {
                    "name": m.text,
                    "taxon": taxon,
                    "title": doc.title,
                    "evidence": {"source": f"PMID:{doc.pmid}",
                                 "text": sentence_at(m.passage_text, m.offset)},
                },
                "expected": expected,
                "gold": {"raw_ids": m.raw_ids, "type": m.ann_type, "passage": m.passage,
                         **({"remapped": remapped} if remapped else {})},
            })
    return cases, excluded
