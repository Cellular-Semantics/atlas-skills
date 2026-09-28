# label-beside-cluster-index

Rule 3 under pressure. `author_cell_type` is the curated answer; `seurat_clusters` is a
20-level categorical of string-encoded integers sitting right beside it. Rejecting the
cluster index must not cost the label.

A good answer names `author_cell_type`, gives a count per label across the 27,034 cells,
and does not present `seurat_clusters` as an author cell-type column. Mentioning it as
rejected is fine.

The numeric check is loose on purpose: it is there to confirm counts were computed from
the pulled column rather than the column name being echoed back. The cell total is
27,034, so any per-label count is below that.

Measured 2026-09-28: 27,034 cells x 39 obs columns.
