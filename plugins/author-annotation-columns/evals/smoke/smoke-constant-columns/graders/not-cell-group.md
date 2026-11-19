---
type: regex
target: { source: file, path: picks.json }
pattern: "\"cell_type\"\\s*:\\s*\\[[^\\]]*\"Cell\\.group\""
match: not_contains
---

`Cell.group` is not picked: rule 4: constant across all cells.
