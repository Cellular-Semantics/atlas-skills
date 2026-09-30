"""Mine a directory of obs profiles for columns worth hand-curating.

Curating a gold set by reading seventy profiles cold is slow and misses things.
This narrows the pool: it reads the column *names* out of each profile and
flags the ones whose name suggests a field type, so a curator opens the profile
already knowing which twenty of its sixty columns to look at hardest.

It is a **curation aid and nothing else**. A name match is not evidence:
`Lineage` matches the age pattern because it contains the letters "age" and is
a cell-type column; `Collection_site` matches the tissue pattern and is an
institution; `Smoker` matches nothing and is still worth looking at. Never load
the output of this module into the gold set. Its job is to decide what a human
reads, not what the answer is.

The complement matters as much: `--miss` lists the columns no pattern caught,
which is where a field type nobody thought to name will be hiding.
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from pathlib import Path

#: Name patterns per field type. Deliberately over-broad -- a false positive
#: costs a curator ten seconds and a false negative costs a gold-set entry.
PATTERNS: dict[str, str] = {
    "tissue": r"tissue|organ|region|layer|anatom|site|dissect|compartment"
              r"|structure|lobe|segment|area",
    "development_stage": r"\bage|_age|age_|stage|develop|gestat|pcw|postnatal"
                         r"|embryo|f[eo]etal|adult|birth|tanner|carnegie",
    "other_stage": r"menstr|[eo]estr|cycle|\bphase\b|puberty",
    "disease": r"disease|diagnos|patholog|condition|covid|cancer|tumou?r"
               r"|severity|healthy|infect|lesion|comorbid|syndrome",
}

#: Columns that match a pattern and are never a pick, so the candidate list
#: does not waste a curator's attention on the same five every time. These are
#: CELLxGENE's standardised fields and the obvious protocol columns.
ALWAYS_REJECT = re.compile(
    r"^(tissue|tissue_type|disease|development_stage|organism|assay|sex"
    r"|self_reported_ethnicity|suspension_type|cell_type|is_primary_data"
    r"|observation_joinid|donor_id)(_ontology_term_id)?$"
    r"|_ontology_term_id$"
    r"|dissociation|preservation|handling|sampling_method|protocol|reagent",
    re.I)


def column_names(profile_text: str) -> list[str]:
    """The column names in a text profile, in order.

    The profile is four header lines then one row per column, pipe-separated
    with the name first. Rows that do not look like that are skipped rather
    than guessed at.
    """
    out = []
    for line in profile_text.splitlines():
        if "|" not in line or line.startswith("name |"):
            continue
        name = line.split("|", 1)[0].strip()
        if name and not name.endswith(":"):
            out.append(name)
    return out


def classify(name: str) -> list[str]:
    """Field types whose name pattern this column matches. Often empty."""
    if ALWAYS_REJECT.search(name):
        return []
    return [ft for ft, pat in PATTERNS.items() if re.search(pat, name, re.I)]


def mine(profiles_dir: str | Path, *, suffix: str = ".txt") -> dict:
    """Candidate columns across a directory of profiles, grouped by field type.

    Each candidate carries how many datasets it appears in and which ones, so a
    curator can start with the names that recur -- they are the ones whose call
    will be reused most.
    """
    profiles_dir = Path(profiles_dir)
    paths = sorted(profiles_dir.glob(f"*{suffix}"))
    if not paths:
        raise FileNotFoundError(f"No *{suffix} profiles under {profiles_dir}")

    hits: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    unmatched: dict[str, set[str]] = defaultdict(set)
    seen = Counter()

    for path in paths:
        dsid = path.stem
        for name in column_names(path.read_text()):
            seen[name] += 1
            fts = classify(name)
            if fts:
                for ft in fts:
                    hits[ft][name].add(dsid)
            elif not ALWAYS_REJECT.search(name):
                unmatched[name].add(dsid)

    def rows(d):
        return [{"column": n, "n_datasets": len(ds), "datasets": sorted(ds)}
                for n, ds in sorted(d.items(), key=lambda kv: (-len(kv[1]), kv[0]))]

    return {
        "profiles_dir": str(profiles_dir),
        "n_profiles": len(paths),
        "n_distinct_columns": len(seen),
        "warning": "Name matches only. Not ground truth, not a pick list -- a "
                   "curator must read the values before any of this becomes a "
                   "gold-set entry.",
        "candidates": {ft: rows(hits[ft]) for ft in PATTERNS},
        "unmatched": rows(unmatched),
    }
