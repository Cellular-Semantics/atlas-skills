# standardised-request-does-not-trigger

The guard against over-triggering. This dataset *does* have author cell-type columns, and
the skill description is about exactly this file — but the user asked for the
standardised `cell_type` field, which is already in obs and needs no picking.

A good answer reads obs with `remote-h5ad-obs` and gives counts per `cell_type` value
across 1,679 cells. Dispatching `author-celltype-picker` is the failure: it spends a
sub-agent answering a question nobody asked.

Mentioning in passing that author columns also exist is fine and arguably helpful. Making
them the answer is not.

Measured 2026-09-28: 1,679 cells; `cell_type_ontology_term_id` has 8 levels.
