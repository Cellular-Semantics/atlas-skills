---
type: regex
target: { source: file, path: picks.json }
pattern: "\"cell_type\"\\s*:\\s*\\[[^\\]]*\"leiden\""
match: not_contains
---

`leiden` is not picked: rule 3: string-encoded integers are a cluster index.
