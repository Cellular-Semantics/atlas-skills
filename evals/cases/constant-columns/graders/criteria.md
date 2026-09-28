# constant-columns

This dataset is an isolated population. `Cell.class`, `Cell.group` and `Lineage` each
have exactly one value across all 7,274 cells, and `cell_type` /
`cell_type_ontology_term_id` are constant too. The CL_KG curators recorded **no**
cell-type field for it.

The correct outcome is to report that there is no usable author cell-type column, and to
say why: the candidates carry a dataset-level fact, not a per-cell assignment. Naming the
single value (e.g. reporting what the whole population is) is useful extra detail.

The failure mode is presenting `Cell.class` or `Lineage` as the author cell-type column
because the name and the value both look right. The frozen n=73 picker picked four
columns here.

An empty pick list is a real answer. An answer that treats it as an error, or that goes
looking for another file, has misread the situation.

**`sub_cluster` is a defensible pick and must not be marked wrong.** It holds `plt_0`
… `plt_4` — sub-clusters within the platelet population, varying per cell. The curation
records nothing for this dataset, so scoring counts it against precision, but it is a
real author annotation and rule 3 explicitly allows mixed letter-and-digit names. An
answer that offers it *while saying the broader columns are constant* is the best
available answer. What is being tested here is the reasoning about constancy, not an
empty list.

Measured 2026-09-28: 7,274 cells x 37 obs columns.
