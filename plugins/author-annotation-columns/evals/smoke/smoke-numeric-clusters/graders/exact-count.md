---
type: regex
target: { source: file, path: picks.json }
pattern: "\"cell_type\"\\s*:\\s*\\[\\s*\"[^\"]*\"\\s*\\]"
---

`picks.cell_type` holds exactly 1 column(s), as curated: `free_annotation`. An extra pick fails this.
