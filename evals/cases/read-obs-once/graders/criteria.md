# read-obs-once

A good answer names `BICCN_class_label` (5 labels: Inhibitory, Excitatory, Unknown, ...)
and `BICCN_cluster_label` (33 labels: Vip, L4, Ndnf, Pvalb, ...) as the author cell-type
columns, gives a distinct-label count for each, and says they are two levels of one
hierarchy.

It should **not** offer `cell_type` or `cell_type_ontology_term_id` — those are
CELLxGENE's standardised annotation, not the authors'.

`BICCN_ontology_term_id` is a defensible extra: it holds author-asserted ILX term ids
rather than a label, and the curation does not list it. Naming it is not a failure;
presenting it as a cell-type *label* column is.

Mechanically: obs should be pulled once with `h5ad-obs <url> --out obs.parquet` and then
profiled locally with `h5ad-obs obs.parquet --profile`. Profiling the URL *and* pulling
obs means two remote reads of the same file, which costs more than either alone.

Measured 2026-09-28: 1,679 cells x 37 obs columns, 1.3 MB fetched.
