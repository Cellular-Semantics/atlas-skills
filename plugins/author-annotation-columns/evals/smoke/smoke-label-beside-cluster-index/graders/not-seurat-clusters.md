---
type: regex
target: { source: file, path: picks.json }
pattern: "\"cell_type\"\\s*:\\s*\\[[^\\]]*\"seurat_clusters\""
match: not_contains
---

`seurat_clusters` is not picked: rule 3: a numeric cluster index.
