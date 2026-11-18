# Evals in this repo

How every plugin here is evaluated, where each kind of eval lives, and what to
run when. Package unit tests (`packages/*/tests`) are covered by `dev.sh` and
CI and are not repeated here. This page is about checking **skill behaviour**
and **answer accuracy**, which need a real agent.

> **Status (2026-11).** This page describes the target layout. Today only
> `author-annotation-columns` has evals in the native format, under the
> top-level `evals/`. The move to this layout is tracked in
> [#27](https://github.com/Cellular-Semantics/atlas-skills/issues/27). Until it lands, `evals/README.md` is the
> how-to for the existing suite.

## Three layers

| Layer | Question | Who runs it | Cost | Lives in |
|---|---|---|---|---|
| **Smoke and behaviour** | Does the skill fire, use the right tools, and avoid the documented traps? Does it give a plausible answer on a handful of known datasets? | Anyone with the plugin: developers, reviewers, users | a few dollars | `plugins/<plugin>/evals/` |
| **Accuracy benchmark** | How often is the answer *correct*, against curated gold, across the whole test set? | Developers, before a release | slow; tens of dollars for a full run | `evals/<plugin>/` |
| **Gold data and metrics** | What counts as correct, and how it is scored | Imported by the benchmark | free | `packages/<name>-eval/` |

The reason for the split: `claude plugin eval` grades with regex, tool-use and
LLM graders but **cannot run code**. Anything scored by a metric (Jaccard,
precision and recall per tier, confidence intervals) needs a script, and so
stays in the repo.

## Layout

```
plugins/<plugin>/evals/            # ships with the plugin; `claude plugin eval` format
  <case>/prompt.md                 # what the agent is asked
  <case>/graders/*.md              # what a good answer looks like

evals/                             # repo-only developer tooling
  README.md                        # index: one row per plugin, what to run, cost
  <plugin>/                        # one directory per plugin with a benchmark
    README.md
    benchmark.py                   # or check.py: code-scored runs
    fixtures/                      # cached inputs, e.g. obs profiles, with PROVENANCE.json
  shared/                          # helpers used by more than one plugin

packages/<name>-eval/              # only when gold data has versions and provenance
  src/<name>/data/                 # snapshot + SOURCE.json, manifest, frozen baselines
  scripts/                         # dev-only: re-snapshot, rebuild manifest
```

## Rules

1. **`plugins/<plugin>/evals/` stays light.** It is installed with the plugin,
   so no large fixtures: a case points at a public dataset URL rather than
   bundling data. Aim for under ~10 cases and under ~$5 for `--tag smoke`.
2. **Every plugin with a skill has at least one `smoke` case.** Then one
   command per plugin checks that it works on someone else's machine:
   ```sh
   claude plugin eval <plugin> --tag smoke
   ```
3. **Tags.** `smoke` (the quick check), `behaviour` (tool choice, traps),
   plus free-form topic tags (`picker`, `tissue`, ...). Keep tags lowercase,
   in kebab-case.
4. **Every benchmark run is logged.** Each run writes one committed file to
   the plugin's run log (`evals/runs/` today, `evals/<plugin>/runs/` after
   #27). The file records the command, the plugin version and commit, the
   exact models, the gold-set version, the metrics, the per-dataset results
   and the cost. An index is generated from the files. Files are never
   overwritten, so the log holds every run, not just the latest. A change in
   accuracy shows up as a diff in review.
5. **Gold data is pinned, never hand-edited.** A snapshot names the upstream
   commit and hashes every file. Fixes are applied on read, in code, with a
   review note. A frozen baseline is re-scored by a test, so a gold change that
   moves an old number fails the build.
6. **Test-set membership is fixed once results are published on it.** Adding
   datasets goes into a separate tier, or comes with a re-scored baseline in
   the same change.
7. **Nothing here runs in CI.** The agent-driven layers cost money and read
   real data. Their graders and scoring code are pure functions, and *those*
   are unit-tested in CI.

## What to run when

| You changed | Run |
|---|---|
| A SKILL.md or agent prompt | `claude plugin eval <plugin> --tag smoke` against a local-scope install |
| Picker or matching logic | the benchmark's default subset, then the full run before release |
| Gold data (new snapshot) | package tests: the frozen-baseline test says whether old numbers moved |
| A release tag | the plugin's full `evals/` suite against the published install |

## Per plugin

| Plugin | Smoke / behaviour | Accuracy benchmark | Gold |
|---|---|---|---|
| author-annotation-columns | 9 cases, in `evals/cases/` (to move) | `evals/benchmark.py` (to move): cell type, n73 + l4 tiers | `packages/obs-column-eval` |
| onto-mapping | none in native format | `evals/ontology-mapping/check.py`, its own harness (to convert) | in-repo JSON cases |
| paper-access | none | none | none |
| remote-h5ad-obs | none (`read-obs-once` touches it indirectly) | none | none |
| atlas-tools | none (empty plugin) | none | none |

## Migration

Tracked in [#27](https://github.com/Cellular-Semantics/atlas-skills/issues/27): move the existing suite into this layout,
convert onto-mapping, add smoke cases for the plugins that have none, and
point `dev.sh`, CI and the READMEs at the new paths.
