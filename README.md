# atlas-skills

Agentic skills for working with published single-cell atlases, plus the packages
they call. Portal-agnostic: these work against any atlas you can reach by URL.

The split is deliberate. **Skills hold judgment** — when to use a capability, how
to read the result, what the traps are. **Packages hold deterministic logic**,
with dependencies, tests and tagged releases. A skill calls code through a CLI;
it never contains non-trivial code.

## Layout

```
packages/h5ad-obs/              remote h5ad obs reader + `h5ad-obs` CLI
packages/celltype-column-eval/  the gold set and metrics for the picker benchmark
plugins/atlas-tools/            the skills and sub-agents, pinned to a package tag
evals/                          skill-behaviour cases + the picker benchmark
docs/                           what the benchmark measured
.claude-plugin/                 marketplace manifest
```

Nothing under `plugins/` imports from, or references by relative path, anything
outside its own directory. Everything a skill needs at runtime arrives as a
pinned, installable dependency — which is what makes the plugin work on a machine
that has only ever seen the plugin directory.

## Install

In Claude Code:

```
/plugin marketplace add Cellular-Semantics/atlas-skills
/plugin install atlas-tools
```

The skills invoke their CLI with `uvx --from git+…@vX.Y.Z`, so the only
prerequisites are `uv` and network access to GitHub on first run. The first call
is slow while uv builds h5py, pandas and aiohttp; cached after that.

## Use the CLI directly

```sh
uvx --from "git+https://github.com/Cellular-Semantics/atlas-skills@v0.2.0#subdirectory=packages/h5ad-obs" \
    h5ad-obs https://datasets.cellxgene.cziscience.com/<id>.h5ad --list-columns
```

stdout is a JSON summary with stable field names, including byte accounting;
the obs table goes to `--out`.

`--profile` prints a per-column summary — kind, cardinality, and sample values
spread across the table — instead of reading obs. It works on a URL, and on an
obs table already pulled to disk:

```sh
h5ad-obs <url> --out obs.parquet      # one remote read
h5ad-obs obs.parquet --profile text   # free
```

## What is here

| skill | does |
|---|---|
| `remote-h5ad-obs` | reads `obs` from a remote `.h5ad` over HTTP range requests, never touching `X` |
| `author-celltype-columns` | works out which `obs` columns hold the authors' own cell-type labels, as opposed to the portal's standardised `cell_type`, cluster indices and QC |

`author-celltype-columns` ships a sub-agent, `author-celltype-picker`, which
makes the judgment call in a fresh context from a column profile. Benchmarked on
73 CELLxGENE datasets against CL_KG hand curation: **Jaccard 0.93, precision
0.94, recall 0.96**, exact agreement on 62 of 73. See
[`docs/benchmark.md`](docs/benchmark.md) for what that does and does not mean —
precision in particular is a lower bound.

## Portal clients live elsewhere

These tools take URLs to files. Resolving a *portal page* to a file URL is
per-portal work and is kept out of this repo, so nothing here depends on a single
data provider. For CAP (`celltype.info`), that is `cap h5ad-url` in
[cap_skills](https://github.com/Cellular-Semantics/cap_skills):

```sh
h5ad-obs "$(cap h5ad-url https://celltype.info/project/934/dataset/3016 --format text)"
```

The two plugins install side by side and are designed to be used together.

## Develop

```sh
./dev.sh              # offline suite
./dev.sh -m live      # also read a real remote h5ad
```

The offline suite runs the whole range-read path against a localhost server that
honours `Range`, including a check that the expression matrix's byte ranges are
never fetched. The live suite reads a 385-cell CELLxGENE Patch-seq dataset,
resolved through the CELLxGENE API at run time so an upstream revision does not
break it; `H5AD_OBS_LIVE_URL` points it at your own host instead.

Skill behaviour is a separate layer, in [`evals/`](evals). Those drive a real
agent and cost money, so they are not in `dev.sh` or CI — but their graders are
pure functions and both are.

The picker's accuracy benchmark re-scores offline: the obs profiles it runs on
are committed fixtures, not fetched.

## Rules for changes

- Deterministic and testable → a package, with tests. About when/how/why → skill text.
- CLI output for agents is JSON-shaped with stable field names, and every CLI
  supports `--version`.
- Changing a CLI contract is a breaking change: bump the version and update every
  pinning skill in the same PR.
- Pin skills to tags, never to a branch.
- No dependency on any single data portal.
