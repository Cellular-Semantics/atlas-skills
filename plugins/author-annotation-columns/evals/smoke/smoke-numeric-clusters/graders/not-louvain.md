---
type: regex
target: { source: file, path: picks.json }
pattern: "\"cell_type\"\\s*:\\s*\\[[^\\]]*\"louvain\""
match: not_contains
---

`louvain` is not picked: rule 3: string-encoded integers are a cluster index.
