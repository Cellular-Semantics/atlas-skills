---
type: regex
target: { source: file, path: picks.json }
pattern: "\"cell_type\"\\s*:\\s*\\[\\s*\"[^\"]*\"\\s*,\\s*\"[^\"]*\"\\s*,\\s*\"[^\"]*\"\\s*,\\s*\"[^\"]*\"\\s*\\]"
---

`picks.cell_type` holds exactly 4 column(s), as curated: `level0`, `level1`, `level1_global`, `level2`. An extra pick fails this.
