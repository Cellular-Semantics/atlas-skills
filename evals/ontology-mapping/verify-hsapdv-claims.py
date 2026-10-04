#!/usr/bin/env python3
"""Check every HsapDv claim in the skill text and eval cases against the ontology.

    python evals/verify-hsapdv-claims.py            # live Ubergraph
    python evals/verify-hsapdv-claims.py --offline   # reuse the cached authority

Written for one job: catching a term, a label, an obsolescence or an interval
number that drifted or was never right. It makes no judgement about whether a
mapping is *correct* -- only about whether the things asserted about HsapDv are
true of HsapDv.

Four claim types:
  1. every HsapDv CURIE mentioned exists
  2. every (CURIE, label) adjacency matches the real label
  3. every label-shaped phrase in prose names a real term, unless the sentence
     exists to say it does not
  4. every start_dpf/end_dpf in the interval tables matches the asserted value
Plus: any obsolete term must be marked obsolete where it is mentioned.

Dependency-free, like check.py. Run it after editing the reference note, after
bumping the HsapDv release, or whenever `oq release -o hsapdv` reports a move.
"""

from __future__ import annotations

import json
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).parent
REPO = ROOT.parent.parent
CACHE = ROOT / ".hsapdv-authority.json"
SPARQL = "https://ubergraph.apps.renci.org/sparql"
GRAPH = "http://purl.obolibrary.org/obo/life-stages/components/hsapdv.owl"
CURIE = r"HsapDv:\d{7}"

TARGETS = [
    "plugins/onto-mapping/skills/map-to-ontology/references/hsapdv.md",
    "plugins/onto-mapping/skills/map-to-ontology/SKILL.md",
    "evals/ontology-mapping/cases-hsapdv.md",
]
# JSON is scanned for CURIEs only: its `record` values are raw corpus strings,
# which are deliberately not ontology labels.
CURIE_ONLY = ["evals/ontology-mapping/cases-hsapdv.json"]

# Label shapes this ontology actually uses. A phrase matching one of these is a
# claim that such a term exists.
SHAPES = re.compile(
    r"\b(\d+(?:st|nd|rd|th) week post-fertilization(?: and over)? stage"
    r"|Carnegie stage \d+[a-c]?"
    r"|\d+(?:st|nd|rd|th) LMP month stage"
    r"|\d+-(?:year|month)-old stage"
    r"|child stage \(1-4 yo\)|juvenile stage \(5-14 yo\)"
    r"|newborn stage \(0-28 days\)|6-12 year-old child stage)\b"
)
NEGATED = re.compile(r"\b(not|no|never|invent|nonexistent|does not exist)\b")


def _sparql(query: str) -> list[dict]:
    req = urllib.request.Request(
        SPARQL,
        data=urllib.parse.urlencode({"query": query}).encode(),
        headers={"Accept": "application/sparql-results+json",
                 "Content-Type": "application/x-www-form-urlencoded",
                 "User-Agent": "verify-hsapdv-claims"},
    )
    with urllib.request.urlopen(req, timeout=90) as r:
        body = json.loads(r.read())
    return [{k: v["value"] for k, v in b.items()} for b in body["results"]["bindings"]]


def _curie(iri: str) -> str:
    return iri.rsplit("/", 1)[-1].replace("HsapDv_", "HsapDv:")


def fetch_authority() -> dict:
    """Labels, obsolescence and dpf bounds, straight from the asserted graph."""
    terms: dict[str, dict] = {}
    for r in _sparql(f"""
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX owl: <http://www.w3.org/2002/07/owl#>
SELECT ?s ?l ?dep WHERE {{ GRAPH <{GRAPH}> {{
  ?s rdfs:label ?l . OPTIONAL {{ ?s owl:deprecated ?dep }} }} }}"""):
        if "HsapDv_" not in r["s"]:
            continue
        terms[_curie(r["s"])] = {"label": r["l"].strip(),
                                 "obsolete": str(r.get("dep", "")).lower() == "true"}
    for r in _sparql(f"""
SELECT ?s ?p ?v WHERE {{ GRAPH <{GRAPH}> {{ ?s ?p ?v .
  VALUES ?p {{ <http://purl.obolibrary.org/obo/hsapdv#start_dpf>
              <http://purl.obolibrary.org/obo/hsapdv#end_dpf> }} }} }}"""):
        c = _curie(r["s"])
        if c in terms:
            terms[c]["start" if r["p"].endswith("start_dpf") else "end"] = float(r["v"])
    return terms


def norm(s: str) -> str:
    """Drop markdown emphasis and line wrapping so prose compares like prose."""
    return re.sub(r"\s+", " ", re.sub(r"\*\*|\*|__|`", "", s)).strip()


def main(argv: list[str]) -> int:
    offline = "--offline" in argv
    if offline:
        if not CACHE.exists():
            print(f"no cached authority at {CACHE}; run once without --offline")
            return 64
        terms = json.loads(CACHE.read_text())
    else:
        terms = fetch_authority()
        CACHE.write_text(json.dumps(terms, indent=0, sort_keys=True) + "\n")

    label = {c: t["label"] for c, t in terms.items()}
    obsolete = {c for c, t in terms.items() if t["obsolete"]}
    by_label = {v.lower(): k for k, v in label.items()}
    problems: list[tuple[str, str, str]] = []
    n = dict(curie=0, pair=0, phrase=0, dpf=0)

    for rel in TARGETS + CURIE_ONLY:
        path = REPO / rel
        raw = path.read_text()

        for c in sorted(set(re.findall(CURIE, raw))):
            n["curie"] += 1
            if c not in label:
                problems.append((rel, "NONEXISTENT CURIE", c))

        if rel in CURIE_ONLY:
            continue
        flat = norm(raw)

        for m in re.finditer(rf"({CURIE})[ |—–-]+([^|]{{3,60}})", flat):
            cid, tail = m.group(1), m.group(2)
            if cid not in label:
                continue
            if tail.lower().startswith(label[cid].lower()):
                n["pair"] += 1
                continue
            for lab, other in by_label.items():
                if tail.lower().startswith(lab) and other != cid:
                    n["pair"] += 1
                    problems.append((rel, "PAIR MISMATCH",
                                     f"{cid} paired with {label[other]!r}; "
                                     f"its own label is {label[cid]!r}"))
                    break

        for m in SHAPES.finditer(flat):
            n["phrase"] += 1
            if m.group(1).lower() in by_label:
                continue
            if NEGATED.search(flat[max(0, m.start() - 70):m.start()].lower()):
                continue  # named in order to say it does not exist
            problems.append((rel, "PHRASE NOT A REAL LABEL", repr(m.group(1))))

        for c in sorted(set(re.findall(CURIE, flat)) & obsolete):
            window = flat[max(0, flat.find(c) - 200):flat.find(c) + 260].lower()
            if "obsolete" not in window:
                problems.append((rel, "OBSOLETE NOT FLAGGED", f"{c} {label[c]!r}"))

        if not rel.endswith("hsapdv.md"):
            continue
        for line in raw.splitlines():
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            ids = [c for c in cells if re.fullmatch(CURIE, c)]
            nums = [c for c in cells if re.fullmatch(r"-?\d+(\.\d+)?", c)]
            if not ids or len(nums) < 2:
                continue
            cid, real = ids[0], terms.get(ids[0], {})
            n["dpf"] += 1
            # Carnegie end_dpf is derived from the next stage, not asserted, so
            # only asserted bounds are compared.
            for key, claimed in (("start", float(nums[0])), ("end", float(nums[1]))):
                if real.get(key) is not None and abs(real[key] - claimed) > 1e-9:
                    problems.append((rel, f"{key.upper()}_DPF WRONG",
                                     f"{cid} says {claimed}, asserted {real[key]}"))

    src = "cached authority" if offline else f"live Ubergraph ({len(terms)} terms)"
    print(f"authority: {src}")
    print(f"checked: {n['curie']} CURIE mentions, {n['pair']} ID:label adjacencies, "
          f"{n['phrase']} label-shaped phrases, {n['dpf']} interval rows")
    if problems:
        print(f"\n{len(problems)} problem(s):")
        for rel, kind, detail in problems:
            print(f"  [{kind}] {rel.split('/')[-1]}: {detail}")
        return 1
    print("\nno discrepancies")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
