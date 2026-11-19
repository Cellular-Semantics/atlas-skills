---
type: regex
target: { source: file, path: picks.json }
pattern: "\"cell_type\"\\s*:\\s*\\[[^\\]]*\"cell_type_ontology_term_id\""
match: not_contains
---

`cell_type_ontology_term_id` is the portal's standardised field, never an author column.
