---
type: regex
target: { source: file, path: picks.json }
pattern: "\"cell_type\"\\s*:\\s*\\[[^\\]]*\"cell_type\""
match: not_contains
---

`cell_type` is the portal's standardised field, never an author column.
