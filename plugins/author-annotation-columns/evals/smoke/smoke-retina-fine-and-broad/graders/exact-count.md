---
type: regex
target: { source: file, path: picks.json }
pattern: "\"cell_type\"\\s*:\\s*\\[\\s*\"[^\"]*\"\\s*,\\s*\"[^\"]*\"\\s*\\]"
---

`picks.cell_type` holds exactly 2 column(s), as curated: `author_cell_type`, `cell_type_group`. An extra pick fails this.
