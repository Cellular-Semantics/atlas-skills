---
name: author-celltype-columns
description: Work out which obs columns in a single-cell dataset hold the authors' own cell-type annotations — `author_cell_type`, `BICCN_subclass_label`, `celltype.l1/l2/l3`, `Cell.class` — as opposed to the portal's standardised `cell_type`, cluster indices, donor ids and QC. Profiles the columns, has a sub-agent judge them, and pulls the ones it picks. Use when someone wants the original labels, finer granularity than CL, or "what the authors actually called these cells".
---

# author-celltype-columns

Portals standardise cell-type annotation onto the Cell Ontology, and that is a
lossy step: the authors' own labels — often several levels of them — survive only
as extra `obs` columns with no naming convention. There is no reliable pattern to
grep for. `author_cell_type`, `BICCN_subclass_label`, `celltype.l3`,
`Cell.group`, `free_annotation`, `precisest_label` and `Re-annotation` are all
real examples from one test set, and so are `seurat_clusters`, `leiden`,
`initial_clustering` and `orig_cluster`, which look just like them and are not
labels at all.

This skill profiles every obs column, hands that profile to the
`author-celltype-picker` sub-agent, and pulls what it picks.

## When to invoke

- "what did the authors call these cells", "the original annotations"
- someone wants finer granularity than the portal's `cell_type`
- marker-encoded or project-convention cluster names
- an atlas comparison that needs author labels rather than harmonised ones

Not needed if the standardised `cell_type` column is what the user wants — read
that directly with `remote-h5ad-obs`.

## Read obs once, then profile it locally

This is the whole shape of the skill, and the ordering matters.

```sh
# 1. one remote read -- this is the expensive step, so do it once
uvx --from "git+https://github.com/Cellular-Semantics/atlas-skills@v0.2.0#subdirectory=packages/h5ad-obs" \
    h5ad-obs <url> --out obs.parquet --block-size 0.25

# 2. profile the file you just pulled -- free, no network
h5ad-obs obs.parquet --profile text > profile.txt
```

Profiling the **URL** instead (`h5ad-obs <url> --profile text`) also works, and
reads less, but it is almost never the right move: whatever it saves you pay
back with interest when you go to the network a second time for the columns the
picker chose. Measured on CELLxGENE:

| obs | profile the URL | read obs whole |
|---|---|---|
| 1,679 × 37 | 1.3 MB, 5 requests | 1.3 MB, 5 requests |
| 115,282 × 34 | 12.6 MB, 6 requests | 16.8 MB, 8 requests |
| 2,282,447 × 70 | 180 MB, 86 requests | 306 MB, 146 requests |

Profiling never saves more than about 40%, and a profile followed by a pull is
two trips past the same HDF5 metadata floor. **Profile the URL only when obs has
millions of rows and you are confident you want very few columns** — otherwise
read obs once and profile the parquet. (Times are not tabulated: they swing by
an order of magnitude with CDN cache state. Bytes are stable.)

`--profile` also accepts `.csv` and `.tsv`, and works on any obs table, not only
one this tool wrote.

## What a profile looks like

```
obs profile: obs.parquet
1679 rows x 37 columns; 1679 rows scanned per column.

name | kind | n_unique | sample values
BICCN_class_label | categorical[5 cats] | 5 | 'Inhibitory', 'Excitatory', 'Unknown', ...
BICCN_cluster_label | categorical[33 cats] | 33 | 'Vip', 'L4', 'Ndnf', 'Pvalb', ...
major_dissection | categorical[1 cats] | 1 (constant) | 'V1', 'V1', 'V1', ...
total_reads | array int64 | 1679 | 23770190, 18388503, 20515208, ...
cell_type_ontology_term_id | categorical[8 cats] | 8 | 'CL:0000617', 'CL:0000679', ...
```

Three things in there do real work:

- **Sample values are spread across the table, not taken from the head.** obs is
  routinely sorted by donor or cluster, and the first twenty rows of a sorted
  column show one value — which reads as a constant column when it is nothing of
  the kind.
- **`(constant)`** means every row was seen and they were all the same. A
  cardinality printed as an estimate (`~7`) came from a sample; `n_scanned` says
  how many rows that was. Only the explicit marker is evidence of constancy.
- The profile carries **no instructions**. The picking rules live in the picker
  agent and nowhere else, so the two cannot drift apart.

## Pick

Dispatch the **`author-celltype-picker`** sub-agent with the `Task` tool,
`subagent_type=author-celltype-picker`, giving it the path to `profile.txt`.

It returns one line of JSON:

```json
{"picks": ["BICCN_class_label", "BICCN_cluster_label"], "reasoning": "..."}
```

Do not pre-filter the profile or tell the agent which columns look promising —
it gets a fresh context precisely so its judgment is independent of yours. For
several datasets, dispatch one agent per dataset in parallel; each must see only
its own profile.

`{"picks": []}` is a real answer, not a failure. Some datasets genuinely have no
author cell-type column — every candidate is constant, or the authors only ever
shipped cluster numbers. Report that as a finding.

## Pull and report

The columns are already in `obs.parquet`; subset it.

```python
import pandas as pd
obs = pd.read_parquet("obs.parquet")
author = obs[["BICCN_class_label", "BICCN_cluster_label"]]
author.value_counts()          # the annotation hierarchy, as used
```

Tell the user: which columns were picked and why, how many distinct labels each
holds, how they nest if there is more than one, and how they line up against the
portal's `cell_type`. A picked column with 33 values against a `cell_type` with
8 is the point of the exercise — say so.

## Traps

- **Show your working.** Benchmarked on 73 CELLxGENE datasets against CL_KG hand
  curation: mean Jaccard 0.93, precision 0.94, recall 0.96, at least one correct
  column in 72/73, and exact agreement on 62 of 73. Good, not settled — name the
  picked columns and their label counts in your answer so the user can see a
  spurious one, rather than presenting the list as fact.
- **A numeric column with many categories is a cluster index, not a label** —
  even when the values are strings. `seurat_clusters`, `leiden`, `louvain`,
  `initial_clustering` and `orig_cluster` all appear in the test set with
  string-typed integers. The picker rejects them; if you see one in the output,
  that is a bug worth reporting.
- **A constant column is not an annotation.** Datasets from an isolated
  population often carry a `Lineage` or `Cell.class` column with one value in
  every cell. It reads like a cell type and carries no information.
- **`cell_type` and `cell_type_ontology_term_id` are the portal's, not the
  authors'.** They are never picks, whatever the user asked for. An
  author-asserted ontology column such as `putative_CL_label` is a different
  thing and is a legitimate pick.
- **Where the picker still errs, it errs by over-picking.** Two known failures in
  73: a numeric cluster index that slipped past the rule, and an anatomical
  `structure` column. Both are visible in the answer if you list what was picked
  — which is the reason to list it.
- **This takes a file URL, not a portal page.** The same rule as
  `remote-h5ad-obs`: the tool refuses a `celltype.info` or `cellxgene.cziscience.com`
  page and tells you what to run instead.

## See also

- `remote-h5ad-obs` — the same reader, for when you just want obs.
- [`packages/celltype-column-eval`](https://github.com/Cellular-Semantics/atlas-skills/tree/main/packages/celltype-column-eval)
  — the gold set and metrics behind the numbers above.
- [`docs/benchmark.md`](https://github.com/Cellular-Semantics/atlas-skills/blob/main/docs/benchmark.md)
  — what the benchmark measured, and what changed since.
