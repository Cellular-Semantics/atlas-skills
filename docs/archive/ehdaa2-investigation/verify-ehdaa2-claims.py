#!/usr/bin/env python3
"""Check every EHDAA2 and Uberon claim in the developmental reference against source.

    python evals/ontology-mapping/verify-ehdaa2-claims.py
    python evals/ontology-mapping/verify-ehdaa2-claims.py --offline

Two authorities, because the reference depends on both and they disagree:

  the released EHDAA2 OWL   existence windows, develops_from, labels, counts
  Ubergraph (uberon-base)   the EHDAA2 <-> Uberon xref bridge

The OWL is the authority for EHDAA2, deliberately. OLS4's term-graph endpoint
drops an `existence_ends_during_or_before` edge whenever it points at the same
stage as the start edge, so a check written against OLS4 would confirm the
reference's own worked examples to be wrong. This script also *tests for* that
data loss, so the day it is fixed upstream we find out.

Claim types checked:
  1. every EHDAA2 CURIE mentioned exists in the release
  2. every (CURIE, label) adjacency matches the real label
  3. every existence window stated in prose or a table matches the OWL
  4. every EHDAA2 -> Uberon xref pair asserted in the text is in Ubergraph
  5. every count asserted in the text recomputes, in its own sentence
  5b. the CS20 ceiling is still where the ontology puts it
  6. each worked navigation row really is refuted, and its answer really is in
     range -- the method's central move, checked rather than asserted
  6. the OLS4 end-bound loss still affects exactly the terms we say it does

It makes no judgement about whether a mapping is biologically right. That is
what the eval cases are for.

Run with `uv run`; the inline metadata pins rdflib and certifi, the latter
because Homebrew's python3 has no CA bundle and fails TLS here otherwise.
"""
# /// script
# requires-python = ">=3.11"
# dependencies = ["rdflib", "certifi"]
# ///

from __future__ import annotations

import argparse
import collections
import json
import re
import sys
import ssl
import time
import urllib.parse
import urllib.request
from pathlib import Path

import certifi

# Homebrew's python has no CA bundle wired up, and uv will happily pick it.
_SSL = ssl.create_default_context(cafile=certifi.where())
_OPENER = urllib.request.build_opener(urllib.request.HTTPSHandler(context=_SSL))
urllib.request.install_opener(_OPENER)

ROOT = Path(__file__).parent
REPO = next(q for q in ROOT.parents if (q / "plugins").is_dir())
CACHE = ROOT / ".ehdaa2-authority.json"
OWL_URL = "http://purl.obolibrary.org/obo/ehdaa2.owl"
SPARQL = "https://ubergraph.apps.renci.org/sparql"
UBERON_GRAPH = "http://purl.obolibrary.org/obo/uberon/uberon-base.owl"
OLS4_GRAPH = "https://www.ebi.ac.uk/ols4/api/ontologies/ehdaa2/terms/{iri}/graph"

EXPECTED_RELEASE = "2024-01-11"

TARGETS = [
    "docs/archive/ehdaa2-investigation/uberon-developmental.md",
    "plugins/onto-mapping/skills/map-to-ontology/SKILL.md",
]
# Scanned for CURIEs and xref pairs only. Its `record` values are annotation
# strings, and its `tests` prose is argument rather than assertion, so the
# label and window regexes would read both as claims about the ontology.
CURIE_ONLY = [
    "docs/archive/ehdaa2-investigation/cases-uberon-developmental.json",
]

EHDAA2_CURIE = r"(?:RETIRED_)?EHDAA2:\d{7}"
UBERON_CURIE = r"UBERON:\d{7}"

# Carnegie stage label -> HsapDv local id, as used by EHDAA2's existence axioms.
CS_TO_HSAPDV = {
    "CS01": 3, "CS02": 5, "CS03": 7, "CS04": 8, "CS05": 9, "CS06": 11,
    "CS07": 13, "CS08": 14, "CS09": 16, "CS10": 17, "CS11": 18, "CS12": 19,
    "CS13": 20, "CS14": 21, "CS15": 22, "CS16": 23, "CS17": 24, "CS18": 25,
    "CS19": 26, "CS20": 27, "CS21": 28, "CS22": 29, "CS23": 30,
}
HSAPDV_TO_CS = {v: k for k, v in CS_TO_HSAPDV.items()}

OBO = "http://purl.obolibrary.org/obo/"
P_START = "RO_0002496"   # existence starts during or after
P_END = "RO_0002497"     # existence ends during or before
P_DEV = "RO_0002202"     # develops from
P_PART = "BFO_0000050"   # part of


# ---------------------------------------------------------------- authority

def load_owl() -> dict:
    """Parse the released EHDAA2 OWL into a plain-JSON authority."""
    import rdflib
    from rdflib import RDF, RDFS, OWL, URIRef

    g = rdflib.Graph()
    # purl.obolibrary.org 500s intermittently; a one-shot fetch makes the whole
    # check flaky for a reason that has nothing to do with the claims.
    for attempt in range(4):
        try:
            g.parse(OWL_URL)
            break
        except Exception as e:  # noqa: BLE001 -- rdflib wraps several
            if attempt == 3:
                raise RuntimeError(f"could not fetch {OWL_URL}: {e}") from None
            time.sleep(2 ** attempt)

    def local(u: str) -> str:
        return str(u).rsplit("/", 1)[-1]

    def curie(u) -> str:
        return local(u).replace("_", ":", 1)

    labels = {}
    for s, _, o in g.triples((None, RDFS.label, None)):
        labels[curie(s)] = str(o)

    rel = collections.defaultdict(lambda: collections.defaultdict(list))
    wanted = {P_START: "start", P_END: "end", P_DEV: "develops_from", P_PART: "part_of"}
    for s, _, r in g.triples((None, RDFS.subClassOf, None)):
        if (r, RDF.type, OWL.Restriction) not in g:
            continue
        p = local(g.value(r, OWL.onProperty))
        v = g.value(r, OWL.someValuesFrom)
        if p in wanted and isinstance(v, URIRef):
            rel[curie(s)][wanted[p]].append(curie(v))

    native = sorted(c for c in labels if c.startswith("EHDAA2:"))
    version = None
    for _, _, o in g.triples((None, URIRef(OWL.versionIRI), None)):
        version = str(o)
        break

    return {
        "version_iri": version,
        "labels": labels,
        "relations": {k: dict(v) for k, v in rel.items()},
        "native": native,
    }


def sparql(query: str) -> list[dict]:
    """POST a query; on failure say which query, since several run per build."""
    body = urllib.parse.urlencode({"query": query}).encode()
    req = urllib.request.Request(
        SPARQL, data=body,
        headers={"Accept": "application/sparql-results+json"},
    )
    head = " ".join(query.split())[:160]
    last = None
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=180) as fh:
                return json.load(fh)["results"]["bindings"]
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as e:
            # Ubergraph 500s and drops connections under load; the aggregate
            # queries below are the ones that trip it.
            last = e
            time.sleep(2 ** attempt)
    raise RuntimeError(f"SPARQL failed after 4 attempts ({last}) on: {head}")


def load_xrefs() -> dict:
    """EHDAA2 id -> [(uberon curie, label)], from Ubergraph."""
    rows = sparql(f"""
        PREFIX oboInOwl: <http://www.geneontology.org/formats/oboInOwl#>
        PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
        SELECT ?x ?u ?label WHERE {{
          GRAPH <{UBERON_GRAPH}> {{
            ?u oboInOwl:hasDbXref ?x . ?u rdfs:label ?label .
          }}
          FILTER(STRSTARTS(STR(?u), "{OBO}UBERON_"))
          FILTER(STRSTARTS(STR(?x), "EHDAA2:") || STRSTARTS(STR(?x), "RETIRED_EHDAA2:"))
        }}
    """)
    out = collections.defaultdict(list)
    for r in rows:
        u = r["u"]["value"].rsplit("/", 1)[-1].replace("UBERON_", "UBERON:")
        out[r["x"]["value"]].append([u, r["label"]["value"]])
    return dict(out)


def load_naming() -> dict:
    """Counts behind the rung-2 substitution advice, from Uberon and GO."""
    rows = sparql(f"""
        PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
        SELECT ?pat (COUNT(DISTINCT ?u) AS ?n) WHERE {{
          GRAPH <{UBERON_GRAPH}> {{ ?u rdfs:label ?l }}
          FILTER(STRSTARTS(STR(?u), "{OBO}UBERON_"))
          BIND(IF(STRSTARTS(LCASE(?l),"future "),"future X",
               IF(STRSTARTS(LCASE(?l),"presumptive "),"presumptive X",
               IF(CONTAINS(LCASE(?l)," primordium"),"X primordium",
               IF(CONTAINS(LCASE(?l)," anlage"),"X anlage",
               IF(CONTAINS(LCASE(?l)," rudiment"),"X rudiment",
               IF(CONTAINS(LCASE(?l)," bud"),"X bud",
               IF(CONTAINS(LCASE(?l),"developing "),"developing X","other")))))))
               AS ?pat)
          FILTER(?pat != "other")
        }} GROUP BY ?pat
    """)
    patterns = {r["pat"]["value"]: int(r["n"]["value"]) for r in rows}

    syn = sparql(f"""
        PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
        PREFIX oboInOwl: <http://www.geneontology.org/formats/oboInOwl#>
        SELECT ?l (GROUP_CONCAT(?s;separator=" ~ ") AS ?syns) WHERE {{
          GRAPH <{UBERON_GRAPH}> {{
            ?u rdfs:label ?l . OPTIONAL {{ ?u oboInOwl:hasExactSynonym ?s }}
          }}
          FILTER(STRSTARTS(STR(?u), "{OBO}UBERON_"))
          FILTER(STRSTARTS(LCASE(?l),"future ") || STRSTARTS(LCASE(?l),"presumptive "))
        }} GROUP BY ?l
    """)

    def cross(prefix, other):
        n = 0
        for r in syn:
            if not r["l"]["value"].lower().startswith(prefix):
                continue
            syns = (r.get("syns", {}).get("value") or "").lower()
            if any(x.strip().startswith(other) for x in syns.split("~")):
                n += 1
        return n

    prec = sparql(f"""
        PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
        PREFIX oboInOwl: <http://www.geneontology.org/formats/oboInOwl#>
        SELECT (COUNT(DISTINCT ?u) AS ?n) (COUNT(DISTINCT ?v) AS ?w) WHERE {{
          GRAPH <{UBERON_GRAPH}> {{
            ?u rdfs:label ?l .
            OPTIONAL {{ ?u oboInOwl:hasDbXref ?x .
                       FILTER(STRSTARTS(STR(?x),"EHDAA2:")
                              || STRSTARTS(STR(?x),"RETIRED_EHDAA2:"))
                       BIND(?u AS ?v) }}
          }}
          FILTER(STRSTARTS(STR(?u),"{OBO}UBERON_"))
          FILTER(STRSTARTS(LCASE(?l),"future ") || STRSTARTS(LCASE(?l),"presumptive ")
                 || CONTAINS(LCASE(?l)," primordium") || CONTAINS(LCASE(?l)," anlage")
                 || CONTAINS(LCASE(?l)," rudiment") || CONTAINS(LCASE(?l)," bud")
                 || CONTAINS(LCASE(?l),"developing "))
        }}
    """)[0]

    # Any anatomy->fetal-stage link anywhere in Ubergraph? The reference claims none.
    weekly = sparql(f"""
        SELECT (COUNT(DISTINCT ?s) AS ?n) WHERE {{
          VALUES ?p {{ <{OBO}RO_0002496> <{OBO}RO_0002497>
                      <{OBO}RO_0002488> <{OBO}RO_0002492> }}
          GRAPH <http://reasoner.renci.org/nonredundant> {{ ?s ?p ?stage . }}
          FILTER(STRSTARTS(STR(?stage),"{OBO}HsapDv_"))
          FILTER(?stage IN ({", ".join(f"<{OBO}HsapDv_{n:07d}>" for n in range(46, 76))}))
        }}
    """)[0]

    go = sparql("""
        PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
        PREFIX oboInOwl: <http://www.geneontology.org/formats/oboInOwl#>
        SELECT (COUNT(DISTINCT ?u) AS ?n_reg) (COUNT(DISTINCT ?v) AS ?n_ctrl) WHERE {
          GRAPH <http://purl.obolibrary.org/obo/go/go-base.owl> {
            ?u rdfs:label ?l .
            OPTIONAL {
              ?u oboInOwl:hasExactSynonym ?s .
              FILTER(CONTAINS(LCASE(?s),"control of")) BIND(?u AS ?v)
            }
          }
          FILTER(STRSTARTS(LCASE(?l),"regulation of"))
        }
    """)[0]

    # direct vs closure, the spinal cord worked example
    def dev_count(graph):
        return len(sparql(f"""
            SELECT ?o WHERE {{
              GRAPH <http://reasoner.renci.org/{graph}> {{
                <{OBO}UBERON_0002240> <{OBO}RO_0002202> ?o .
              }}
              FILTER(STRSTARTS(STR(?o),"{OBO}UBERON_"))
            }}
        """))

    return {
        "patterns": patterns,
        "future_with_presumptive": cross("future ", "presumptive "),
        "presumptive_with_future": cross("presumptive ", "future "),
        "go_regulation": int(go["n_reg"]["value"]),
        "go_with_control_syn": int(go["n_ctrl"]["value"]),
        "precursor_terms": int(prec["n"]["value"]),
        "precursor_with_ehdaa2": int(prec["w"]["value"]),
        "weekly_fetal_links": int(weekly["n"]["value"]),
        "spinal_cord_dev": {g: dev_count(g)
                            for g in ("nonredundant", "redundant", "ontology")},
    }


def build_authority() -> dict:
    a = load_owl()
    a["xrefs"] = load_xrefs()
    a["naming"] = load_naming()
    return a


# ------------------------------------------------------------------ checks

def window(auth: dict, curie: str) -> tuple[str | None, str | None]:
    """(start CS, end CS) for an EHDAA2 term, from the OWL. None where unasserted."""
    rel = auth["relations"].get(curie, {})

    def cs(key):
        vs = rel.get(key, [])
        if not vs:
            return None
        n = int(vs[0].split(":")[1])
        return HSAPDV_TO_CS.get(n, vs[0])

    return cs("start"), cs("end")


def check_curies_exist(auth, texts, fail):
    known = set(auth["labels"])
    xrefs = auth["xrefs"]
    for path, text in texts:
        for c in sorted(set(re.findall(EHDAA2_CURIE, text))):
            if c.startswith("RETIRED_"):
                if c not in xrefs:
                    fail(path, f"{c} is not an xref value in Uberon")
            elif c not in known:
                # The reference names retired ids in their bare form too, to show
                # that the bare form is what silently returns nothing.
                if f"RETIRED_{c}" not in xrefs:
                    fail(path, f"{c} is not in the EHDAA2 {EXPECTED_RELEASE} "
                               "release and is not a retired xref either")


def check_label_adjacency(auth, texts, fail):
    """`EHDAA2:0001570 pronephros` -- the label beside a CURIE must be its label.

    Only phrases that are themselves a real EHDAA2 label are judged. Prose
    following a CURIE ("EHDAA2:0000997 has 0 descendants") is not a label claim,
    and the failure worth catching is a CURIE paired with some *other* term's
    label, which this sees and loose prose does not trip.
    """
    by_label = {v.lower(): k for k, v in auth["labels"].items()}
    pat = re.compile(rf"({EHDAA2_CURIE})`?\s+([a-z][a-z0-9 /()-]{{2,48}}?)(?=[,.;:|`\n])")
    for path, text in texts:
        for c, claimed in pat.findall(text):
            if c.startswith("RETIRED_"):
                continue
            real = auth["labels"].get(c)
            phrase = claimed.strip().lower()
            if real is None or phrase not in by_label:
                continue
            if phrase != real.lower():
                fail(path, f"{c} labelled {claimed.strip()!r}, which is "
                           f"{by_label[phrase]}; ontology says {real!r}")


def check_windows(auth, texts, fail):
    """Every `CS11 - CS18` / `CS09 only` / `CS13 - (no end asserted)` claim."""
    row = re.compile(
        rf"`({EHDAA2_CURIE})`\s*([a-z][a-z0-9 ]*?)\s*\|\s*"
        r"(CS\d\d)\s*(only|-\s*CS\d\d|-\s*\(no end asserted\))"
    )
    inline = re.compile(rf"`({EHDAA2_CURIE})[^`]*`[^.]{{0,80}}?(CS\d\d) to (CS\d\d)")
    for path, text in texts:
        for c, _label, start, tail in row.findall(text):
            if tail == "only":
                want_end = start
            elif tail.endswith(")"):
                want_end = None
            else:
                want_end = tail.split("CS")[-1]
                want_end = f"CS{want_end}"
            got = window(auth, c)
            if got != (start, want_end):
                fail(path, f"{c} window claimed ({start}, {want_end}), OWL says {got}")
        for c, start, end in inline.findall(text):
            got = window(auth, c)
            if got != (start, end):
                fail(path, f"{c} window claimed ({start}, {end}), OWL says {got}")


def check_xref_pairs(auth, texts, fail):
    """An EHDAA2 CURIE and a Uberon CURIE claimed to be the same term must be xrefed.

    Only pairs that actually claim identity are judged. A markdown table pairs
    them only when its header names both ontologies -- the crosswalk tables do,
    while a table whose columns are "refuted because" and "answer" deliberately
    puts two *different* terms on one row. Outside tables, the pair must not be
    separated by a cell boundary.
    """
    inline = re.compile(
        rf"({EHDAA2_CURIE})[^\n|]{{0,120}}?({UBERON_CURIE})"
        rf"|({UBERON_CURIE})[^\n|]{{0,120}}?({EHDAA2_CURIE})"
    )

    def judge(path, e, u):
        targets = [t[0] for t in auth["xrefs"].get(e, [])]
        if targets and u not in targets:
            fail(path, f"{e} shown with {u}; Uberon xrefs it to {targets}")

    for path, text in texts:
        in_xref_table = False
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("|"):
                if re.match(r"\|[\s|:-]+\|?$", stripped):
                    continue  # the ---|--- separator
                header = {c.strip().lower() for c in stripped.strip("|").split("|")}
                if "ehdaa2" in header and "uberon" in header:
                    in_xref_table = True
                    continue
                if in_xref_table:
                    cells = [c.strip() for c in stripped.strip("|").split("|")]
                    es = [c for cell in cells for c in re.findall(EHDAA2_CURIE, cell)]
                    us = [c for cell in cells for c in re.findall(UBERON_CURIE, cell)]
                    if len(es) == 1 and len(us) == 1:
                        judge(path, es[0], us[0])
                    continue
                in_xref_table = False  # a table that does not name both ontologies
                continue
            in_xref_table = False
            for m in inline.finditer(line):
                judge(path, m.group(1) or m.group(4), m.group(2) or m.group(3))


def check_counts(auth, texts, fail):
    """Each count must appear in its own sentence, not merely somewhere in the file.

    Binding every number to a context phrase is the point. A bare
    "is 224 mentioned anywhere" check passes when one of two occurrences drifts,
    which is exactly how a stale number survives an edit.
    """
    native = auth["native"]
    rel = auth["relations"]
    starts = sum(1 for c in native if rel.get(c, {}).get("start"))
    ends = sum(1 for c in native if rel.get(c, {}).get("end"))
    devs = sum(1 for c in native if rel.get(c, {}).get("develops_from"))
    single = [
        c for c in native
        if rel.get(c, {}).get("end")
        and set(rel[c].get("start", [])) == set(rel[c]["end"])
    ]
    multi = ends - len(single)
    one_parent = sum(
        1 for c in native if len(rel.get(c, {}).get("develops_from", [])) == 1
    )
    max_parents = max(
        (len(rel.get(c, {}).get("develops_from", [])) for c in native), default=0
    )
    ub = {k: v for k, v in auth["xrefs"].items() if k.startswith("EHDAA2:")}
    ret = {k: v for k, v in auth["xrefs"].items() if k.startswith("RETIRED_")}
    ambiguous = sum(1 for v in ub.values() if len({u for u, _ in v}) > 1)

    # Carnegie substages (CS05a-CS06b) carry no dpf, so a bracket anchored to one
    # cannot be reached from an age. They cluster in the extraembryonic branch.
    subs = {31, 32, 33, 34, 35}
    substage_terms = [
        c for c in native
        if any(int(v.split(":")[1]) in subs
               for k in ("start", "end") for v in rel.get(c, {}).get(k, []))
    ]
    substage = len(substage_terms)
    substage_xrefed = sum(
        1 for c in substage_terms
        if auth["xrefs"].get(c) or auth["xrefs"].get(f"RETIRED_{c}")
    )
    somite_hole = sum(
        1 for c in single if auth["labels"].get(c, "").startswith("somite")
    )

    # (name, value, context regex -- {n} is where the number must appear)
    claims = [
        ("native classes", len(native), r"\*\*{n}\*\* are native EHDAA2"),
        ("with start bound", starts, r"`existence starts during or after` \| {n} "),
        ("with end bound", ends, r"`existence ends during or before` \| {n} "),
        ("with develops_from", devs, r"`develops_from` \| {n} "),
        ("single-stage terms", len(single), r"{n} EHDAA2 classes exist at"),
        ("single-stage terms (restated)", len(single), r"all\s+{n} whose end equals"),
        ("multi-stage terms", multi, r"the {n} whose\s+end differs"),
        ("classes with an end bound (restated)", ends,
         r"of the {n} classes with an end bound"),
        ("distinct EHDAA2 ids xrefed", len(ub), r"{n} distinct EHDAA2 ids"),
        ("uberon classes xrefing EHDAA2", len({u for v in ub.values() for u, _ in v}),
         r"\*\*{n} Uberon classes carry"),
        ("EHDAA2 ids mapping to >1 Uberon class", ambiguous,
         r"only {n} EHDAA2 ids\s+map to more than one Uberon class"),
        ("RETIRED ids", len(ret), r"carry {n} such ids"),
        ("uberon classes with a RETIRED xref",
         len({u for v in ret.values() for u, _ in v}), r"{n} Uberon classes carry \d+ such"),
        ("develops_from terms with one parent", one_parent,
         r"{n} have exactly one parent"),
        ("max develops_from parents", max_parents, r"the maximum is (?:five|{n})"),
        ("substage-anchored classes", substage, r"\*\*{n} classes are anchored to"),
        ("substage-anchored with a Uberon xref", substage_xrefed,
         r"of which {n} carry a\s+Uberon xref"),
        ("affected somite terms", somite_hole, r"{n} of\s+the affected 224"),
    ]
    text = "\n".join(t for _, t in texts)
    for name, n, ctx in claims:
        word = {5: "five", 2: "two"}.get(n, "")
        pat = ctx.replace("{n}", f"(?:{n:,}|{n}" + (f"|{word}" if word else "") + ")")
        # the reference is hard-wrapped at 79 columns, so any literal space in a
        # context pattern may be a newline plus indent in the file
        pat = re.sub(r"(?<!\\)(?<!\\s)\s(?![*+?{])", r"\\s+", pat)
        if not re.search(pat, text):
            fail("counts", f"{name} = {n} is not stated in its own sentence "
                           f"(looked for /{pat}/)")
    return {
        "native classes": len(native), "with start bound": starts,
        "with end bound": ends, "with develops_from": devs,
        "single-stage (start == end)": len(single),
        "distinct EHDAA2 ids xrefed": len(ub),
        "uberon classes carrying one": len({u for v in ub.values() for u, _ in v}),
        "RETIRED ids": len(ret),
        "uberon classes carrying a RETIRED one":
            len({u for v in ret.values() for u, _ in v}),
    }


def check_naming_advice(auth, texts, fail):
    """The rung-2 substitution advice rests on counts; check them.

    These are the numbers that make "generate the variants yourself" an argument
    rather than an opinion, so they are the ones worth catching when they drift.
    """
    n = auth.get("naming")
    if not n:
        fail("naming", "authority predates the naming counts; refetch without --offline")
        return
    text = "\n".join(t for _, t in texts)

    claims = [(f"{pat} count", v, rf"\|\s*`?{re.escape(pat)}`?\s*\|\s*{v}\s*\|")
              for pat, v in n["patterns"].items()]
    claims += [
        ("total precursor terms", sum(n["patterns"].values()),
         r"{n} terms for one idea"),
        ("future with presumptive synonym", n["future_with_presumptive"],
         r"only {n} of the \d+ `future X` terms carry"),
        ("presumptive with future synonym", n["presumptive_with_future"],
         r"only {n} of the \d+ the reverse|and only {n} of the \d+ the reverse"),
        ("GO regulation terms", n["go_regulation"], r"\*\*{n}\*\* terms are named"),
        ("GO with control synonym", n["go_with_control_syn"],
         r"exactly \*\*{n}\*\* carry"),
        ("spinal cord direct develops_from", n["spinal_cord_dev"]["nonredundant"],
         r"there\s+is exactly \*\*(?:one|{n})\*\*"),
        ("precursor terms", n["precursor_terms"], r"the {n} terms named with one"),
        ("precursor terms with a bracket", n["precursor_with_ehdaa2"],
         r"only \*\*{n}\s*\(\d+%\)\*\* carry an EHDAA2 xref"),
    ]
    if n["weekly_fetal_links"] != 0:
        fail("naming", f"{n['weekly_fetal_links']} terms now link to a weekly fetal "
                       "HsapDv stage; the reference says none do, and the 'no fetal "
                       "resource' claim needs rewriting")
    for name, v, ctx in claims:
        pat = ctx.replace("{n}", str(v))
        pat = re.sub(r"(?<!\\)(?<!\\s)\s(?![*+?{])", r"\\s+", pat)
        if not re.search(pat, text):
            fail("naming", f"{name} = {v} is not stated where expected "
                           f"(looked for /{pat}/)")

    for g, want in n["spinal_cord_dev"].items():
        if not re.search(rf"{g}\s+UBERON:0002240 develops_from\s+->\s+"
                         rf"(?:{want} terms|posterior neural tube)", text):
            fail("naming", f"the {g} graph returns {want} develops_from edges for "
                           "spinal cord; the worked block does not say so")


def check_sweep_counts(auth, texts, fail):
    """Recompute the sweep's refutation counts and compare with the stated table.

    Only the count columns are checkable. Whether a refutation is *sound* is a
    judgement over 25 cases that no ontology can settle, so that column is
    unguarded by construction and the reference says so.

    Skipped when the corpus is not on this machine.
    """
    sweep = ROOT / "sweep-hdca-corpus.py"
    corpus = Path(
        "/Users/do12/Documents/GitHub/HDCA_metadata/reports/embryonic_tissue_fields.csv"
    )
    if not (sweep.exists() and corpus.exists()):
        print("sweep counts: skipped (corpus not present on this machine)")
        return
    import subprocess
    r = subprocess.run(["uv", "run", str(sweep), str(corpus)],
                       capture_output=True, text=True, cwd=REPO)
    got = dict(re.findall(r"^\s+(exact|substitution|substring)\s+(\d+) distinct",
                          r.stdout, re.M))
    if not got:
        fail("sweep", f"could not read counts from the sweep: {r.stdout[-200:]}")
        return
    text = "\n".join(t for _, t in texts)
    rows = {
        "exact": r"\| exact label \| (\d+) \|",
        "substitution": r"\| rung-2 substitution \| (\d+) \|",
        "substring": r"\| substring / token overlap \| (\d+) \|",
    }
    for how, pat in rows.items():
        stated = re.findall(pat, text)
        if not stated:
            fail("sweep", f"no table row states the {how} refutation count")
            continue
        if any(v != got[how] for v in stated):
            fail("sweep", f"{how} refutations: sweep says {got[how]}, "
                          f"the reference says {stated}")
    print(f"sweep counts: exact {got['exact']}, substitution {got['substitution']}, "
          f"substring {got['substring']} (soundness column is unguarded by design)")


def check_claimed_absences(auth, texts, fail):
    """A term the text says has no Uberon xref must really have none.

    An absence is a claim like any other, and it is the kind that rots quietly:
    the xref gets added upstream and the warning in the reference becomes a lie
    that nothing else in the file contradicts.
    """
    pat = re.compile(
        rf"`({EHDAA2_CURIE})[^`]*`[^.]{{0,120}}?no Uberon xref", re.IGNORECASE
    )
    for path, text in texts:
        for c in pat.findall(text):
            if auth["xrefs"].get(c) or auth["xrefs"].get(f"RETIRED_{c}"):
                targets = auth["xrefs"].get(c) or auth["xrefs"][f"RETIRED_{c}"]
                fail(path, f"{c} is said to have no Uberon xref, but it has "
                           f"{[t[0] for t in targets]}")


def check_navigation_table(auth, texts, fail):
    """The three worked navigation rows must actually work.

    Each row claims: this stage is refuted by that EHDAA2 term's window, and
    this Uberon term is the answer. Both halves are checkable. The second half
    is the one worth checking -- an answer whose own bracket also excludes the
    stage would be a worked example that does not work.
    """
    rev = collections.defaultdict(list)
    for ehdaa2_id, pairs in auth["xrefs"].items():
        for u, _ in pairs:
            rev[u].append(ehdaa2_id.replace("RETIRED_", ""))

    row = re.compile(
        rf"\|\s*`[^`]+`\s+at\s+(CS\d\d)\s*\|\s*`({EHDAA2_CURIE})`[^|]*\|"
        rf"[^|]*\|\s*`({UBERON_CURIE})`"
    )
    seen = 0
    for path, text in texts:
        for stage, refuted, answer in row.findall(text):
            seen += 1
            n = CS_TO_HSAPDV.get(stage)

            start, end = window(auth, refuted)
            lo = CS_TO_HSAPDV.get(start) if start else None
            hi = CS_TO_HSAPDV.get(end) if end else None
            if not ((lo and n < lo) or (hi and n > hi)):
                fail(path, f"{refuted} window ({start}, {end}) does not actually "
                           f"exclude {stage}, but the table says it refutes")

            counterparts = rev.get(answer, [])
            if not counterparts:
                fail(path, f"{answer} is offered as the answer for {stage} but has "
                           "no EHDAA2 xref, so its bracket cannot be checked")
                continue
            ok = False
            for c in counterparts:
                s2, e2 = window(auth, c)
                lo2 = CS_TO_HSAPDV.get(s2) if s2 else None
                hi2 = CS_TO_HSAPDV.get(e2) if e2 else None
                if (lo2 is None or n >= lo2) and (hi2 is None or n <= hi2):
                    ok = True
            if not ok:
                windows = [(c, window(auth, c)) for c in counterparts]
                fail(path, f"{answer} is offered as the answer for {stage}, but its "
                           f"EHDAA2 counterpart excludes that stage: {windows}")
    if seen < 3:
        fail("navigation", f"only {seen} navigation rows found; the table that "
                           "carries the method's central move has shrunk")


def check_stage_ceiling(auth, texts, fail):
    """The CS20 ceiling is load-bearing: it bounds what the whole route can do."""
    stages = set()
    for c in auth["native"]:
        for key in ("start", "end"):
            for v in auth["relations"].get(c, {}).get(key, []):
                stages.add(int(v.split(":")[1]))
    carnegie = {n for n in stages if n in HSAPDV_TO_CS}
    hi, lo = max(carnegie), min(carnegie)
    hi_cs, lo_cs = HSAPDV_TO_CS[hi], HSAPDV_TO_CS[lo]
    text = "\n".join(t for _, t in texts)

    if not re.search(rf"`HsapDv:{hi:07d}`\s*\(\*\*{hi_cs}\*\*\)", text):
        fail("ceiling", f"highest stage actually used is {hi_cs} "
                        f"(HsapDv:{hi:07d}); the text does not say so")
    if not re.search(rf"`HsapDv:{lo:07d}`\s*\({lo_cs}\)", text):
        fail("ceiling", f"lowest stage actually used is {lo_cs} "
                        f"(HsapDv:{lo:07d}); the text does not say so")
    unused = sorted(
        cs for n, cs in HSAPDV_TO_CS.items() if n > hi
    )
    for cs in unused:
        # "Nothing points at CS21" is the claim we want, not a violation of it.
        if re.search(rf"(?<!Nothing )points at {cs}\b", text):
            fail("ceiling", f"text claims a stage target at {cs}, but nothing "
                            f"above {hi_cs} is used")
    return hi_cs, lo_cs


def check_ols4_end_loss(auth, fail, sample=12):
    """The reference says OLS4 drops end bounds that equal the start. Still true?"""
    rel = auth["relations"]
    same = [
        c for c in auth["native"]
        if rel.get(c, {}).get("end")
        and set(rel[c].get("start", [])) == set(rel[c]["end"])
    ][:sample]
    diff = [
        c for c in auth["native"]
        if rel.get(c, {}).get("end")
        and set(rel[c].get("start", [])) != set(rel[c]["end"])
    ][:sample]

    def has_end(c):
        iri = urllib.parse.quote(
            urllib.parse.quote(OBO + c.replace(":", "_"), safe=""), safe=""
        )
        with urllib.request.urlopen(OLS4_GRAPH.format(iri=iri), timeout=90) as fh:
            d = json.load(fh)
        local = c.replace(":", "_")
        return any(
            e["label"] == "existence ends during or before"
            and e["source"].endswith(local)
            for e in d["edges"]
        )

    lost = [c for c in same if not has_end(c)]
    kept = [c for c in diff if has_end(c)]
    if len(lost) != len(same):
        fail("ols4", f"end-bound loss no longer universal: {len(lost)}/{len(same)} "
                     "single-stage terms lost it. If OLS4 is fixed, rewrite the "
                     "warning section and the kidney example.")
    if len(kept) != len(diff):
        fail("ols4", f"OLS4 now also drops end bounds that differ from the start: "
                     f"only {len(kept)}/{len(diff)} kept. The hole is bigger than "
                     "the reference says.")
    return len(lost), len(same), len(kept), len(diff)


# -------------------------------------------------------------------- main

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--offline", action="store_true",
                    help="reuse the cached authority instead of refetching")
    ap.add_argument("--skip-ols4", action="store_true",
                    help="skip the OLS4 end-bound-loss probe (24 slow requests)")
    args = ap.parse_args()

    if args.offline:
        if not CACHE.exists():
            print(f"no cache at {CACHE}; run once without --offline", file=sys.stderr)
            return 2
        auth = json.loads(CACHE.read_text())
    else:
        auth = build_authority()
        CACHE.write_text(json.dumps(auth))

    if auth.get("version_iri") and EXPECTED_RELEASE not in auth["version_iri"]:
        print(f"NOTE: EHDAA2 has moved off {EXPECTED_RELEASE} "
              f"({auth['version_iri']}). Every window below is from the new "
              f"release; the reference says it was written against the old one.")

    texts = []
    for rel_path in TARGETS:
        p = REPO / rel_path
        if p.exists():
            texts.append((rel_path, p.read_text()))

    curie_only = []
    for rel_path in CURIE_ONLY:
        p = REPO / rel_path
        if p.exists():
            curie_only.append((rel_path, p.read_text()))

    failures: list[tuple[str, str]] = []

    def fail(where, msg):
        failures.append((where, msg))

    check_curies_exist(auth, texts + curie_only, fail)
    naming_targets = texts
    check_xref_pairs(auth, curie_only, fail)
    check_label_adjacency(auth, texts, fail)
    check_windows(auth, texts, fail)
    check_xref_pairs(auth, texts, fail)
    counts = check_counts(auth, texts, fail)
    check_navigation_table(auth, texts, fail)
    check_claimed_absences(auth, texts, fail)
    check_sweep_counts(auth, texts, fail)
    check_naming_advice(auth, texts + curie_only, fail)
    hi_cs, lo_cs = check_stage_ceiling(auth, texts, fail)

    print(f"stage targets used: {lo_cs} to {hi_cs}")
    print("counts recomputed from source:")
    for k, v in counts.items():
        print(f"  {v:>6}  {k}")

    if not args.skip_ols4:
        lost, n_same, kept, n_diff = check_ols4_end_loss(auth, fail)
        print(f"\nOLS4 end-bound loss: {lost}/{n_same} single-stage terms lost it, "
              f"{kept}/{n_diff} differing-stage terms kept it")

    print()
    if failures:
        for where, msg in failures:
            print(f"FAIL  {where}: {msg}")
        print(f"\n{len(failures)} failed")
        return 1
    print("all claims check out")
    return 0


if __name__ == "__main__":
    sys.exit(main())
