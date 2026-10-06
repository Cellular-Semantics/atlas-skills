#!/usr/bin/env python3
"""Sweep every in-range HDCA (stage, tissue) pair through the EHDAA2 brackets.

    uv run evals/ontology-mapping/sweep-hdca-corpus.py [corpus.csv]

Offline apart from the cached authority, so the whole corpus costs nothing to
re-run. It decides nothing -- it produces the refutations, grouped by how the
EHDAA2 candidate was matched, so a person can judge them.

The grouping is the point. Swept over 557 atomic (stage, component) checks,
every refutation from an exact or substituted match held up, and 23 of the 25
from substring matching were nonsense produced by a shared word -- 'Membrane'
matching 'anal membrane', 'stroma' matching 'corneal stroma mesenchyme'. The
reference's rule, refute only on a match you would defend, comes from this
output. Re-running it is how we find out when that stops being true.

Needs .ehdaa2-authority.json; run verify-ehdaa2-claims.py once to build it.
"""
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
import csv, json, re, collections, sys, pathlib

ROOT = pathlib.Path(__file__).parent
AUTH = ROOT / ".ehdaa2-authority.json"
CORPUS = (sys.argv[1] if len(sys.argv) > 1 else
          "/Users/do12/Documents/GitHub/HDCA_metadata/reports/embryonic_tissue_fields.csv")

if not AUTH.exists():
    sys.exit(f"no authority at {AUTH}; run verify-ehdaa2-claims.py first")

AUTH="/Users/do12/Documents/GitHub/skills/atlas-skills-uberon/evals/ontology-mapping/.ehdaa2-authority.json"
a=json.load(open(AUTH)); lab=a["labels"]; rel=a["relations"]; xr=a["xrefs"]
CS={3:1,5:2,7:3,8:4,9:5,11:6,13:7,14:8,16:9,17:10,18:11,19:12,20:13,21:14,22:15,23:16,24:17,25:18,26:19,27:20}
def win(c):
    r=rel.get(c,{}); f=lambda k: CS.get(int(r[k][0].split(":")[1])) if r.get(k) else None
    return f("start"), f("end")
def ubx(c):
    r=xr.get(c) or xr.get("RETIRED_"+c); return r[0] if r else None

native={c:l for c,l in lab.items() if c.startswith("EHDAA2:")}
by_exact={}
for c,l in native.items(): by_exact.setdefault(l.lower(), c)

# rung-2 substitutions, applied to the whole string and to its head noun
SUBS=[("upper limb","forelimb"),("lower limb","hindlimb"),("forelimb","upper limb"),
      ("hindlimb","lower limb"),("future ","presumptive "),("presumptive ","future "),
      (" primordium",""),(" anlage",""),(" rudiment",""),(" bud",""),
      ("developing ",""),("mesencephalon","midbrain"),("prosencephalon","forebrain"),
      ("rhombencephalon","hindbrain"),("diencephalon","diencephalon"),
      ("cerebral cortex","future cerebral cortex"),("cortex","future cerebral cortex"),
      ("corpus striatum","future corpus striatum"),("striatum","future corpus striatum"),
      ("medulla","medulla oblongata"),("vertebrae","vertebra"),("vertebral column","vertebra"),
      ("gonad","gonad primordium"),("tract","system"),("great vessels","great vessel")]

def variants(s):
    """Ordered, exact spellings first.

    This must be a list, not a set. Python randomises string hashing per
    process, so set iteration order varies between runs and the same input
    matched `exact` on one run and `substitution` on the next -- which silently
    changed the headline numbers this script exists to produce.
    """
    s = s.strip()
    out = [s, s.lower(), s.lower().rstrip("s")]
    for a_, b_ in SUBS:
        if a_ in s.lower():
            out.append(s.lower().replace(a_, b_).strip())
    seen, ordered = set(), []
    for v in out:
        if v and v not in seen:
            seen.add(v)
            ordered.append(v)
    return ordered

def atoms(s):
    """Split composite annotation strings into the things they actually name."""
    parts=re.split(r"\s*[;|]\s*", s)
    return [p.strip() for p in parts if p.strip()]

def match(term):
    """exact -> variant-exact -> substring. Returns (curie, how) or (None, None)."""
    for v in variants(term):
        if v in by_exact: return by_exact[v], ("exact" if v==term.strip().lower() else "substitution")
    toks=[t for t in term.lower().split() if len(t)>3]
    if toks:
        cands=sorted(c for c,l in native.items() if all(t in l.lower() for t in toks))
        if cands: return min(cands,key=lambda c:(len(native[c]),c)), "substring"
    return None, None

F=CORPUS
rows=[r for r in csv.DictReader(open(F)) if r["embryonic_call"]=="confirmed"]
def csn(r):
    m=re.match(r"Carnegie stage (\d+)$", r["development_stage_label"]); return int(m.group(1)) if m else None
JUNK={"missing","Homo sapiens","embryo","section one","section two","not applicable","na","NA",""}
inr=[r for r in rows if csn(r) and csn(r)<=20 and r["tissue_value"].strip() not in JUNK and not r["tissue_value"].startswith("UBERON:")]
pairs=collections.Counter((csn(r), r["tissue_value"].strip()) for r in inr)

res=[]
for (n,t),cnt in pairs.items():
    for at in atoms(t):
        c,how=match(at)
        if c is None:
            res.append((n,t,at,None,None,None,"no EHDAA2 candidate",cnt)); continue
        s,e=win(c)
        if s is None: verdict="no bracket"
        elif n<s: verdict="REFUTED too early"
        elif e and n>e: verdict="REFUTED too late"
        else: verdict="in range"
        res.append((n,t,at,c,how,(s,e),verdict,cnt))
json.dump(res,open(ROOT/"sweep-latest.json","w"))
v=collections.Counter(r[6] for r in res); h=collections.Counter(r[4] for r in res if r[4])
print("atomic (stage, component) checks:",len(res))
print("verdicts:",dict(v))
print("how matched:",dict(h))

ref=[r for r in res if r[6].startswith("REFUTED")]
dis={(r[2],r[0],r[3]):r for r in ref}
print(f"\nrefutations: {len(ref)} instances, {len(dis)} distinct (component, stage, candidate)")
for how in ("exact","substitution","substring"):
    d=[v for v in dis.values() if v[4]==how]
    print(f"  {how:13} {len(d):3} distinct  -- {'judge each' if how=='substring' else 'trustworthy'}")
print("\nevery refutation, for judging:")
for k,v in sorted(dis.items(), key=lambda i:(i[1][4], i[0][0])):
    n,t,at,c,how,w,verdict,cnt=v
    print(f"  [{how:12}] CS{n:02d} {at!r:32} -> {c} {lab[c]!r} {w}  (~{cnt} rows)")
