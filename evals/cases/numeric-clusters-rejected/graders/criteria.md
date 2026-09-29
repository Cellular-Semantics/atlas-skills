# numeric-clusters-rejected

The curated answer is `free_annotation` alone.

`leiden` (25 levels) and `louvain` (19 levels) are categoricals whose values are integers
stored as strings — `'12'`, `'9'`, `'18'`. They are cluster indices. The frozen n=73
picker took all three columns; rule 3 in the picker agent exists because of datasets
like this one.

A good answer returns `free_annotation` and either does not mention the cluster columns
or mentions them explicitly as rejected. Naming them as author cell-type columns is the
failure. The deterministic checks only fire on `leiden`/`louvain` appearing close to
picking language, because an answer that says "I rejected leiden and louvain because
their values are integers" is a *better* answer, not a worse one.

Measured 2026-09-28: 7,249 cells x 32 obs columns.
