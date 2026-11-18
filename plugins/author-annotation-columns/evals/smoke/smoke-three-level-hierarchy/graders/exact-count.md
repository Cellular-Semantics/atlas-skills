---
type: regex
target: { source: file, path: picks.json }
pattern: "\"cell_type\"\\s*:\\s*\\[\\s*\"[^\"]*\"\\s*,\\s*\"[^\"]*\"\\s*,\\s*\"[^\"]*\"\\s*\\]"
---

`picks.cell_type` holds exactly 3 column(s), as curated: `celltype.l1`, `celltype.l2`, `celltype.l3`. An extra pick fails this.
