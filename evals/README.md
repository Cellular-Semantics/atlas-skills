# Skill evals

The second test layer the repo rules ask for. `packages/*/tests/` check
deterministic logic; these check **skill behaviour** — does the right skill fire
from an intent-shaped prompt, does the agent reach for the right flag, does it
read the result correctly and avoid the documented traps.

Two arms, answering two different questions.

## `runner.py` — does the skill behave

```sh
python3 evals/runner.py                        # every case, one run each
python3 evals/runner.py --case 'read-obs-*'    # a subset
python3 evals/runner.py --tag picker           # by tag
python3 evals/runner.py --dry-run              # print the prompts, spend nothing
python3 evals/runner.py --runs 3               # three runs per case, for flakiness
```

Needs the plugin installed (`claude plugin install atlas-tools@atlas-skills
--scope user`) — the cases test the **published** plugin, not the working tree,
so a SKILL.md edit needs a push plus `claude plugin marketplace update
atlas-skills` before it shows up here.

Each case runs in a fresh temporary directory, so nothing but the user-scope
plugin is in scope: no project `CLAUDE.md`, no `.claude/skills`.

**These cost money and read real h5ads from the CELLxGENE CDN.** About
$0.20–0.50 per run, ~$2 for the suite. One run per case by default;
`--max-cost-usd` (default 8) aborts a suite that runs away. Not in CI.

### The cases

| case | pins |
|---|---|
| `read-obs-once` | obs is pulled once and profiled locally, not fetched twice |
| `numeric-clusters-rejected` | `leiden` / `louvain` are cluster indices, not labels |
| `constant-columns` | a dataset where every candidate is constant has no author column |
| `annotation-hierarchy` | all three levels of `celltype.l1/l2/l3`, not just the finest |
| `label-beside-cluster-index` | rejecting `seurat_clusters` does not cost `author_cell_type` |
| `standardised-request-does-not-trigger` | a request for the portal's `cell_type` must not spend a picker |

Each is one of the six datasets in the benchmark subset, so a failure here and a
failure there point at the same file.

## `benchmark.py` — is the picker correct

```sh
python3 evals/benchmark.py                 # the six default datasets
python3 evals/benchmark.py --all           # all 74; slow, not free
python3 evals/benchmark.py --profiles-only # refresh the profile cache, no agent
```

Scored against the CL_KG gold set in `packages/celltype-column-eval`, and
reported next to the frozen n=73 picker on the same datasets, so a change is
visible as a delta rather than an absolute. See
[`docs/benchmark.md`](../docs/benchmark.md).

Two stages. Profiling is deterministic, needs no agent, and is cached under
`evals/.cache/profiles/` — a rerun costs no bandwidth. Picking dispatches the
published sub-agent, three at a time by default.

To run either arm against the working tree before a tag exists:

```sh
H5AD_OBS_CMD="packages/h5ad-obs/.venv/bin/h5ad-obs" python3 evals/benchmark.py
```

## Layout

```
cases/<name>/prompt.md              what the agent is asked
cases/<name>/checks.json            deterministic checks + tags + limits
cases/<name>/graders/criteria.md    what a good answer looks like, in prose
graders.py                          pure grading logic
runner.py                           subprocess driver for the behaviour arm
benchmark.py                        profile -> pick -> score, for the accuracy arm
test_graders.py, test_cases.py      unit tests for the graders (free, offline)
```

`prompt.md` + `graders/criteria.md` is the layout `claude plugin eval` expects,
so the cases migrate to it unchanged when it leaves early access — only
`runner.py` and `checks.json` are throwaway. `plugin eval` additionally brings a
no-plugin **ablation arm**, which these lack and which matters: without it, a
case a bare model could answer from latent knowledge scores the same as one the
skill actually earned.

`graders.py` is shared with
[cap_skills](https://github.com/Cellular-Semantics/cap_skills); keep the two in
step so cases stay portable.

## Check kinds

| kind | matches against |
|---|---|
| `command_matches` / `command_not_matches` | every tool call's name and JSON input |
| `answer_matches` / `answer_not_matches` | the final answer |
| `answer_any_of` | word-bounded list, with `min_hits` |
| `numeric_present` | any number in the answer falling in `[min, max]` |
| `numeric_in_range` | a number captured by an anchored `pattern` |

Every check carries a `why` saying what behaviour it pins, printed on failure.
Anything not expressible deterministically belongs in `criteria.md` for an LLM
grader to judge.

## Writing a rejection check without punishing a better answer

Most cases here pin a column the picker must **not** choose. The naive check —
`answer_not_matches: "leiden"` — fails the best possible answer, the one that
says "I rejected `leiden` because its values are integers". So the negative
checks match the column name only near picking language, and `test_cases.py`
asserts both directions for every one of them: the answer that should pass does,
and the answer that should fail does.

Run those free, before spending anything:

```sh
python3 -m pytest evals -q
```

## Brittleness

The cases assert the **content of live third-party datasets**. A CELLxGENE
re-ingest or a revised annotation can move them. Expectations were measured on
**2026-09-28** and each `criteria.md` records what was there then; when one
fails, check whether the dataset changed before assuming the skill did.

The CDN URL is keyed on `dataset_id` and is stable across revisions, but the
obs columns behind it are not.

## Infrastructure versus regression

A run stopped by a spend or rate limit is reported separately and not counted as
a failure — `graders.INFRA_MARKERS` lists what that looks like. Scoring those as
failures buries a real regression under noise. Rerun them.
