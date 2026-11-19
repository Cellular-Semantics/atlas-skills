---
type: regex
target: { source: file, path: picks.json }
pattern: "\"cell_type\"\\s*:\\s*\\[[^\\]]*\"level0_global\""
match: not_contains
---

`level0_global` is not picked: rule 4: constant across all cells.
