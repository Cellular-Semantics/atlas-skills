---
type: regex
target: { source: file, path: picks.json }
pattern: "\"cell_type\"\\s*:\\s*\\[[^\\]]*\"Cell\\.class\""
match: not_contains
---

`Cell.class` is not picked: rule 4: constant across all cells.
