"""Which release of an ontology each backend is actually serving.

Two backends answer the same questions about the same ontology, and nothing
guarantees they loaded the same release. OLS4 reloads on its own schedule;
Ubergraph rebuilds on another. When they disagree, an answer assembled from
both is assembled from two different ontologies, and the disagreement is
silent -- every call still succeeds.

So: ask both, compare, and cache the answer by date. A skill that holds a
written reference to a specific release can also pass ``expect`` and find out
that its notes have gone stale.

Nothing here decides what to do about a mismatch. It reports one.
"""

from __future__ import annotations

import datetime as _dt
import json
import os
import re
from collections.abc import Mapping
from pathlib import Path

from .transport import Transport
from .ubergraph import Ubergraph

# Most OBO releases are dated, and the date is in the version IRI even when the
# ontology forgot to assert owl:versionInfo.
_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")

CACHE_ENV = "ONTO_QUERY_CACHE"
CACHE_NAME = "releases.json"

# Day granularity on purpose. Neither backend reloads more than once a day, so
# re-asking within a day costs two requests and tells you what you already know.
DEFAULT_MAX_AGE_DAYS = 1


def _version_from_iri(iri: str | None) -> str | None:
    if not iri:
        return None
    m = _DATE.search(iri)
    return m.group(0) if m else None


def state_base(os_name: str, environ: Mapping[str, str], home: str) -> str:
    """The platform's per-user state directory, as a plain string.

    Separate from the Path construction below so it can be tested for Windows
    on a posix box -- `pathlib` refuses to build a WindowsPath there, so the
    only way to exercise the branch is to keep the choice out of `pathlib`.
    """
    if os_name == "nt":
        return environ.get("LOCALAPPDATA") or os.path.join(home, "AppData", "Local")
    return environ.get("XDG_STATE_HOME") or os.path.join(home, ".local", "state")


def default_cache_path() -> Path:
    """Per-user state file, outside any repo and never committed.

    ``$ONTO_QUERY_CACHE`` wins if set. Otherwise the platform's state location:
    ``%LOCALAPPDATA%`` on Windows, ``$XDG_STATE_HOME`` (default
    ``~/.local/state``) everywhere else. This is cached state, not
    configuration and not a user document -- losing it costs two requests.
    """
    if env := os.environ.get(CACHE_ENV):
        return Path(env).expanduser()
    base = state_base(os.name, os.environ, os.path.expanduser("~"))
    return Path(base) / "onto-query" / CACHE_NAME


def read_cache(path: Path) -> dict:
    """A damaged cache is not an error. It is a cache."""
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def write_cache(path: Path, data: dict) -> str | None:
    """Returns a warning if the write failed. Never raises: a read-only
    filesystem should cost you the cache, not the answer."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=1, sort_keys=True) + "\n")
        tmp.replace(path)
    except OSError as exc:
        return f"could not write the release cache at {path}: {exc}"
    return None


def _age_days(checked: str | None, today: _dt.date) -> int | None:
    if not checked:
        return None
    try:
        return (today - _dt.date.fromisoformat(checked[:10])).days
    except ValueError:
        return None


def ols4_release(transport: Transport, ontology: str) -> dict:
    """Version as OLS4 reports it, plus when OLS4 last loaded the ontology."""
    doc = transport.ols4_ontology(ontology)
    cfg = doc.get("config") or {}
    version_iri = cfg.get("versionIri")
    return {
        "version": cfg.get("version") or _version_from_iri(version_iri),
        "version_iri": version_iri,
        "loaded": doc.get("loaded"),
        "present": bool(doc.get("ontologyId")),
    }


def ubergraph_release(ug: Ubergraph, ontology: str) -> dict:
    """Version from the ontology header in Ubergraph's per-ontology graph."""
    graph = ug.graph_for(ontology)
    if graph is None:
        return {"version": None, "version_iri": None, "graph": None, "present": False}
    rows = ug.query(f"""
SELECT ?info ?viri WHERE {{
  GRAPH <{graph}> {{
    ?s a owl:Ontology .
    OPTIONAL {{ ?s owl:versionInfo ?info }}
    OPTIONAL {{ ?s owl:versionIRI ?viri }}
  }}
}}""")
    info = next((r["info"] for r in rows if r.get("info")), None)
    viri = next((r["viri"] for r in rows if r.get("viri")), None)
    return {
        "version": info or _version_from_iri(viri),
        "version_iri": viri,
        "graph": graph,
        "present": True,
    }


def check(
    transport: Transport,
    ontology: str,
    *,
    expect: str | None = None,
    cache_path: Path | None = None,
    max_age_days: int = DEFAULT_MAX_AGE_DAYS,
    refresh: bool = False,
    today: _dt.date | None = None,
) -> dict:
    """Compare the release each backend serves, caching the result by date.

    A cache entry younger than ``max_age_days`` is returned without touching
    the network; ``from_cache`` says which happened, so a caller can tell a
    fresh agreement from a remembered one.
    """
    today = today or _dt.date.today()
    path = cache_path or default_cache_path()
    cache = read_cache(path)
    previous = cache.get(ontology)
    warnings: list[str] = []

    age = _age_days((previous or {}).get("checked"), today)
    fresh = previous is not None and age is not None and 0 <= age < max_age_days
    if fresh and not refresh:
        result = dict(previous)
        result["from_cache"] = True
        result["cache_age_days"] = age
    else:
        ols4 = ols4_release(transport, ontology)
        ug = ubergraph_release(Ubergraph(transport), ontology)
        result = {
            "ontology": ontology,
            "checked": today.isoformat(),
            "ols4": ols4,
            "ubergraph": ug,
            # Tri-state on purpose. False must mean "they serve different
            # releases", not "one of them does not have it" -- those call for
            # different handling, and the warnings say which happened.
            "agree": (
                (ols4["version"] is not None and ols4["version"] == ug["version"])
                if (ols4["present"] and ug["present"] and (ols4["version"] or ug["version"]))
                else None
            ),
            "from_cache": False,
            "cache_age_days": 0,
        }
        transient = ("from_cache", "cache_age_days")
        cache[ontology] = {k: v for k, v in result.items() if k not in transient}
        if w := write_cache(path, cache):
            warnings.append(w)

    ols4, ug = result["ols4"], result["ubergraph"]
    result["cache"] = str(path)

    if not ols4["present"]:
        warnings.append(f"{ontology} is not in OLS4; its version could not be read")
    if not ug["present"]:
        warnings.append(
            f"{ontology} is not in Ubergraph; reasoning is unavailable for it "
            "and only the OLS4 version is reported"
        )
    if ols4["present"] and ug["present"]:
        if result["agree"] is False:
            warnings.append(
                f"BACKENDS DISAGREE: OLS4 serves {ols4['version']!r} and Ubergraph "
                f"serves {ug['version']!r}. Answers combining the two combine two "
                "different releases; say which backend each claim came from."
            )
        elif result["agree"] is None:
            warnings.append(
                "neither backend reports a version for this ontology, so agreement "
                "could not be established"
            )

    if expect is not None:
        result["expected"] = expect
        seen = {v for v in (ols4["version"], ug["version"]) if v}
        result["matches_expected"] = seen == {expect}
        if not result["matches_expected"]:
            warnings.append(
                f"expected {expect!r} but the backends serve {sorted(seen) or ['nothing']}; "
                "any written reference pinned to the expected release may be stale"
            )

    if previous and not result["from_cache"]:
        moved = {
            b: (previous[b]["version"], result[b]["version"])
            for b in ("ols4", "ubergraph")
            if previous.get(b, {}).get("version") != result[b]["version"]
        }
        result["previous"] = {"checked": previous.get("checked"), "changed": moved or None}
        if moved:
            warnings.append(
                "release changed since the last check on "
                f"{previous.get('checked')}: "
                + "; ".join(f"{b} {old!r} -> {new!r}" for b, (old, new) in moved.items())
            )

    result["warnings"] = warnings
    return result
