---
type: regex
target: { source: file, path: picks.json }
pattern: "\"cell_type\"\\s*:\\s*\\[[^\\]]*\"Lineage\""
match: not_contains
---

`Lineage` is not picked: rule 4: constant across all cells.
