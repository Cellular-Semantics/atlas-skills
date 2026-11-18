#!/usr/bin/env python3
"""Bring ``data/manifest.json`` in line with the curation snapshot.

    python3 packages/obs-column-eval/scripts/extend_manifest.py [--profiles evals/fixtures/profiles]

Dev-only, and idempotent: every run recomputes the manifest from the curation
sheets plus whatever profiles exist, so the usual loop is

    1. scripts/snapshot_clkg.py <sha>        # new sheets
    2. scripts/extend_manifest.py            # new versions -> tier "l4"
    3. evals/benchmark.py --all --profiles-only
    4. scripts/extend_manifest.py            # choose between duplicate versions

The rules it applies:

- **The n73 tier is frozen.** Its 74 entries keep their ids and shape; they only
  gain ``tier``, ``cxg_dataset_ids`` and ``aliases``. Four CELLxGENE datasets
  are in it twice, under two versions each. That stays -- it is what the 0.940
  was measured on -- and the aliases make it visible.
- **One version per CELLxGENE dataset in l4.** A dataset already in n73 adds
  nothing to l4. Otherwise, if the sheets name several versions, keep the one
  whose curated cell-type columns all exist in its obs, then the first readable
  one, and record the rest as ``aliases``. Until every candidate has a profile
  the group is kept whole and marked ``pending_choice``; step 4 settles it, and
  deletes the profiles of the versions it drops. A settled choice is kept on
  later runs: the evidence for it (the dropped profiles) is gone by then.
- Versions with no h5ad link cannot be keyed, and are reported, not guessed.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "packages" / "obs-column-eval" / "src"))

from obs_column_eval.curation import CURATION_DIR, UUID_RE, parse_curation  # noqa: E402
from obs_column_eval.manifest import MANIFEST_PATH  # noqa: E402

CDN = "https://datasets.cellxgene.cziscience.com/{}.h5ad"


def _sheets() -> tuple[dict[str, dict], list[str]]:
    """version -> {cxg ids, groups}; and the CxG datasets with no version."""
    versions: dict[str, dict] = defaultdict(lambda: {"cxg": set(), "groups": set()})
    unkeyed = set()
    for path in sorted(CURATION_DIR.glob("*.csv")):
        with path.open(newline="", encoding="utf-8") as fh:
            for raw in csv.DictReader(fh):
                row = {(k or "").strip(): (v or "").strip() for k, v in raw.items()}
                link = row.get("CxG Link") or row.get("CxG link") or ""
                cxg = UUID_RE.search(link)
                ver = UUID_RE.search(row.get("h5ad link", ""))
                if not ver:
                    if cxg:
                        unkeyed.add(cxg.group(1))
                    continue
                entry = versions[ver.group(1)]
                entry["groups"].add(path.stem)
                if cxg:
                    entry["cxg"].add(cxg.group(1))
    return versions, sorted(unkeyed)


def _profile(profiles: Path, version: str) -> dict | None:
    """Shape and column names from a committed text profile, if there is one."""
    path = profiles / f"{version}.txt"
    if not path.exists():
        return None
    lines = path.read_text().splitlines()
    head = lines[1].split()
    names = {line.split(" | ", 1)[0] for line in lines[4:] if " | " in line}
    return {"n_cells": int(head[0]), "n_obs_columns": int(head[3]), "columns": names}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--rechoose", action="store_true",
                    help="Re-decide duplicate-version groups instead of keeping an "
                         "earlier choice. Needs every member's profile on disk.")
    ap.add_argument("--profiles", type=Path, default=ROOT / "evals" / "fixtures" / "profiles")
    args = ap.parse_args()

    versions, unkeyed = _sheets()
    curated = parse_curation()  # cell-type columns per version, corrections applied
    all_rows = parse_curation(filter_celltype=False)
    old = json.loads(MANIFEST_PATH.read_text())
    missing_reason = {}
    prov_path = args.profiles / "PROVENANCE.json"
    if prov_path.exists():
        missing_reason = json.loads(prov_path.read_text()).get("missing", {})

    by_cxg: dict[str, set[str]] = defaultdict(set)
    for ver, info in versions.items():
        for cxg in info["cxg"]:
            by_cxg[cxg].add(ver)

    def aliases(ver: str) -> list[str]:
        return sorted({v for cxg in versions[ver]["cxg"] for v in by_cxg[cxg]} - {ver})

    manifest: dict[str, dict] = {}

    # --- n73: frozen; annotate only.
    n73 = {v for v, e in old.items() if e.get("tier", "n73") == "n73"}
    for ver in sorted(n73):
        entry = {k: v for k, v in old[ver].items()
                 if k not in ("tier", "cxg_dataset_ids", "aliases")}
        entry["tier"] = "n73"
        entry["cxg_dataset_ids"] = sorted(versions[ver]["cxg"])
        if aliases(ver):
            entry["aliases"] = aliases(ver)
        manifest[ver] = entry
    n73_cxg = {c for v in n73 for c in versions[v]["cxg"]}

    # --- l4: everything else, one version per CELLxGENE dataset.
    pool = {v for v in versions if v not in n73
            and not (versions[v]["cxg"] & n73_cxg)}
    # Versions that share a CxG dataset form one group (union over shared ids).
    groups: list[frozenset[str]] = []
    for ver in sorted(pool):
        linked = [g for g in groups if any(versions[x]["cxg"] & versions[ver]["cxg"] for x in g)]
        merged = frozenset({ver}.union(*linked))
        groups = [g for g in groups if g not in linked] + [merged]

    dropped, pending = [], []
    for group in sorted(groups, key=lambda g: sorted(g)[0]):
        members = sorted(group)
        chosen, reason = members, None
        settled = next((v for v in members if old.get(v, {}).get("chosen_because")
                        and set(old[v].get("aliases", [])) | {v} == set(members)), None)
        if len(members) > 1 and settled and not args.rechoose:
            # Decided on an earlier run, whose dropped profiles are gone by now.
            chosen, reason = [settled], old[settled]["chosen_because"]
            dropped += [v for v in members if v != settled]
        elif len(members) > 1:
            profs = {v: _profile(args.profiles, v) for v in members}
            if any(p is None and v not in missing_reason for v, p in profs.items()):
                reason = "pending_choice"
                pending.append(members)
            else:
                readable = [v for v in members if profs[v]]
                complete = [v for v in readable
                            if set(curated.get(v, {}).get("columns", [])) <= profs[v]["columns"]]
                # "All curated columns present" holds trivially for a version
                # curated with none, so among the complete ones prefer the
                # fuller curation: most cell-type columns, then most rows.
                def fullness(v: str) -> tuple[int, int]:
                    return (len(curated.get(v, {}).get("columns", [])),
                            len(all_rows.get(v, {}).get("columns", [])))
                ranked = sorted(complete, key=lambda v: (-fullness(v)[0], -fullness(v)[1], v))
                pick = (ranked or readable or members)[0]
                if not complete:
                    reason = "first readable version" if readable else "none readable"
                elif len({fullness(v) for v in complete}) > 1:
                    reason = ("curated columns all present in obs; fullest curation "
                              f"({fullness(pick)[0]} cell-type columns)")
                else:
                    reason = "curated columns all present in obs; versions tie, first by id"
                chosen = [pick]
                dropped += [v for v in members if v != pick]
        for ver in chosen:
            prof = _profile(args.profiles, ver)
            entry = {
                "url": CDN.format(ver),
                "group": sorted(versions[ver]["groups"])[0],
                "n_cells": prof["n_cells"] if prof else None,
                "n_obs_columns": prof["n_obs_columns"] if prof else None,
                "tier": "l4",
                "cxg_dataset_ids": sorted(versions[ver]["cxg"]),
            }
            others = [v for v in members if v != ver] if reason != "pending_choice" else []
            if others:
                entry["aliases"] = others
                entry["chosen_because"] = reason
            if reason == "pending_choice":
                entry["pending_choice"] = True
            manifest[ver] = entry

    for ver in dropped:
        stale = args.profiles / f"{ver}.txt"
        if stale.exists():
            stale.unlink()
    if prov_path.exists():
        # Keep the provenance record in step with the files actually present.
        prov = json.loads(prov_path.read_text())
        kept = {v: e for v, e in prov.get("profiles", {}).items()
                if (args.profiles / f"{v}.txt").exists()}
        if len(kept) != len(prov.get("profiles", {})):
            prov["profiles"] = kept
            prov["n_datasets"] = len(kept)
            prov["total_bytes"] = sum(e["bytes"] for e in kept.values())
            prov_path.write_text(json.dumps(prov, indent=2) + "\n")

    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2) + "\n")
    tiers = defaultdict(int)
    for e in manifest.values():
        tiers[e["tier"]] += 1
    print(f"manifest: {dict(tiers)}  ({len(manifest)} entries)")
    print(f"  without a profile yet: {sum(1 for v, e in manifest.items() if e['n_cells'] is None and v not in missing_reason)}")
    if pending:
        print(f"  duplicate-version groups awaiting profiles: {len(pending)}")
    if dropped:
        print(f"  dropped as aliases: {', '.join(dropped)}")
    if unkeyed:
        print(f"  CxG datasets with no h5ad link (not scorable): {', '.join(unkeyed)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
