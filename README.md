# atlas-skills

Agentic skills for working with published single-cell atlases and the literature
behind them, plus the packages they call. Portal-agnostic: these work against
any atlas you can reach by URL.

**Each skill is its own plugin, and installs on its own.** Nothing here is
all-or-nothing: take the one you want.

The split is deliberate. **Skills hold judgment** — when to use a capability, how
to read the result, what the traps are. **Packages hold deterministic logic**,
with dependencies, tests and tagged releases. A skill calls code through a CLI;
it never contains non-trivial code.

## Layout

```
packages/h5ad-obs/                 remote h5ad obs reader + `h5ad-obs` CLI
packages/obs-column-eval/          gold sets and metrics for the picker benchmarks
packages/paper-access/             paper retrieval + `paper-access` CLI
plugins/remote-h5ad-obs/           one skill
plugins/author-annotation-columns/ one skill + the two picker sub-agents
plugins/paper-access/              one skill + the identifier-provenance hooks
plugins/atlas-tools/               a bundle of the two h5ad plugins; no skills of its own
evals/                             skill-behaviour cases + the picker benchmarks
docs/                              what the benchmarks measured
.claude-plugin/                    marketplace manifest
```

Nothing under `plugins/` imports from, or references by relative path, anything
outside its own directory. Everything a skill needs at runtime arrives as a
pinned, installable dependency — which is what makes the plugin work on a machine
that has only ever seen the plugin directory.

## Install

Install into the project you are working in, rather than globally:

```sh
claude plugin marketplace add Cellular-Semantics/atlas-skills --scope local
claude plugin install remote-h5ad-obs@atlas-skills --scope local
```

Install whichever plugins you want; they are independent. `atlas-tools` is a
convenience bundle that pulls in the two h5ad plugins and nothing else — it
carries no skills itself, so installing it and installing both separately give
the same result.

`--scope local` writes `.claude/settings.local.json`, which is gitignored by
convention: the plugin is available in this checkout, for you, and nowhere else.
Nothing leaks into your other projects and nothing is committed. Remove it with
`claude plugin uninstall remote-h5ad-obs@atlas-skills --scope local`.

The three scopes, and when each is right:

| scope | written to | who gets it |
|---|---|---|
| `local` | `.claude/settings.local.json` (gitignored) | you, in this checkout |
| `project` | `.claude/settings.json` (committed) | everyone who clones the repo |
| `user` | `~/.claude/settings.json` | you, everywhere |

`user` is the default if you omit `--scope`, which is usually more than you
meant. Prefer `local` to try something out, `project` to give a repo's whole team
the same tools.

The skills invoke their CLI with `uvx --from git+…@vX.Y.Z`, so the only
prerequisites are `uv` and network access to GitHub on first run. The first call
is slow while uv builds h5py, pandas and aiohttp; cached after that.

### Setting it up for a repo

To make these tools part of a repository's setup — so anyone who clones it has
them without being told to install anything — install at **project** scope from
inside that repo:

```sh
claude plugin marketplace add Cellular-Semantics/atlas-skills --scope project
claude plugin install remote-h5ad-obs@atlas-skills --scope project
```

That writes `.claude/settings.json`. **Commit it.**

```json
{
  "extraKnownMarketplaces": {
    "atlas-skills": {
      "source": { "source": "github", "repo": "Cellular-Semantics/atlas-skills" }
    }
  },
  "enabledPlugins": {
    "remote-h5ad-obs@atlas-skills": true
  }
}
```

You can equally write that file by hand and skip the two commands — it is the
whole of the configuration. A fresh clone picks the plugin up from it with no
install step, resolving to whatever version the marketplace currently publishes.

Two things worth knowing:

- It layers rather than replaces. Someone who already has the plugin at user
  scope keeps that too; the project-scope copy takes precedence in this repo.
- Pin deliberately if you need to. The marketplace tracks the default branch, so
  a clone gets the current release, not the one you tested against. For
  reproducible analysis, pin the *package* instead by calling the CLI directly
  with a tagged `uvx --from` line (see below) rather than relying on the plugin.

To add these tools to a repo whose `.claude/settings.json` already exists, merge
the two keys into it rather than overwriting.

## Use the CLI directly

```sh
uvx --from "git+https://github.com/Cellular-Semantics/atlas-skills@pkg-h5ad-obs--v0.3.0#subdirectory=packages/h5ad-obs" \
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

| plugin | skill | does |
|---|---|---|
| `remote-h5ad-obs` | `remote-h5ad-obs` | reads `obs` from a remote `.h5ad` over HTTP range requests, never touching `X` |
| `author-annotation-columns` | `author-annotation-columns` | works out which `obs` columns hold the authors' own cell type, tissue, developmental stage or disease, as opposed to the portal's standardised fields, cluster indices, protocol and QC |
| `paper-access` | `paper-access` | retrieves a list of papers as tagged article XML where it can be had, probes how much of each a search index holds, and names the papers nobody can reach |
| `paper-access` | `retrieve-supplements` | fetches a paper's supplementary files, reading the list and the publisher's captions out of the article XML, and refuses to download half a gigabyte without asking |

`author-annotation-columns` takes a `field_type` of `cell_type`, `tissue`,
`development_stage`, `other_stage` or `disease`, and ships two sub-agents that
make the judgment call in a fresh context from a column profile.

**`author-celltype-picker`** is benchmarked on 73 CELLxGENE datasets against
CL_KG hand curation: **Jaccard 0.94, precision 0.96, recall 0.96**, exact
agreement on 63 of 73. See [`docs/benchmark.md`](docs/benchmark.md) for what
that does and does not mean — precision in particular is a lower bound.

**`author-sample-field-picker`** covers tissue, stage and disease. It has no
comparable number yet: its gold set is one hand-curated atlas, and the
73-dataset candidate pool it was written against has not been curated. Treat its
picks as a proposal. See [`docs/sample-fields.md`](docs/sample-fields.md).

### paper-access

Takes DOIs, PMIDs, PMCIDs or rough citations. Walks **JATS XML → ASTA index
probe → open-access PDF → ask a person**, in that order: reading a whole paper
beats retrieving from it, and article XML is the only source that carries
reference markup, document order and figure legends. The ASTA probe runs for
every paper regardless of how it arrived, because no API field reports snippet
coverage and the band is what tells a later multi-paper search which papers it
can reach.

Identifiers and publication metadata enter a record from exactly two places —
the caller, or a named API at a recorded time — and the plugin ships hooks that
enforce it: a direct write to an `availability.json` is denied, and with
`PAPER_ACCESS_STORE` set, identifiers quoted in a written document are checked
against the store.

### retrieve-supplements

The same plugin's second skill. Reads a paper's supplement list and the
publisher's captions out of the article XML already on disk, then fetches from
the publisher's host, Europe PMC's bundle or the preprint server. A download
over 50 MB is **deferred** rather than capped: the record carries its size and
the flag that would proceed, because a limit nobody was told about looks like a
paper with fewer supplements than it has.

It does not look inside anything. No spreadsheet is opened and no relevance
judged; a retrieved file is an opaque blob with a label. Working out which file
answers a question is a separate job, and a retrieval record deliberately has no
relevance field so that "not yet judged" cannot be read as "judged
irrelevant". See
[`docs/supplement-retrieval-plan.md`](docs/supplement-retrieval-plan.md).

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

## Releasing

Each plugin versions independently, and so does each package. A repo-wide tag
would mean an h5ad release forcing a re-pin in a plugin that does not use it.

```sh
claude plugin tag plugins/remote-h5ad-obs     # remote-h5ad-obs--v0.3.0
```

`claude plugin tag` checks that `plugin.json` and the marketplace entry agree
before it writes the tag, and its format is fixed: `<plugin-name>--v<version>`.

**Package tags carry a `pkg-` prefix** — `pkg-paper-access--v0.1.0` — and are
what the `uvx --from …@<tag>` lines in the skills pin to. The prefix is not
decoration: a plugin and the package it calls may share a name, and where they
do, an unprefixed package tag would collide with the plugin tag at the same
version number. One tag cannot mean two things, and the collision only bites
when the two versions happen to coincide, which is exactly when nobody is
looking for it.

## Rules for changes

- Deterministic and testable → a package, with tests. About when/how/why → skill text.
- CLI output for agents is JSON-shaped with stable field names, and every CLI
  supports `--version`.
- Changing a CLI contract is a breaking change: bump the version and update every
  pinning skill in the same PR.
- Pin skills to tags, never to a branch. Tags are per package and per plugin,
  `<name>--v<version>`, never repo-wide.
- One skill per plugin, unless two genuinely cannot be used apart. A user should
  be able to take the one thing they want.
- No dependency on any single data portal.
