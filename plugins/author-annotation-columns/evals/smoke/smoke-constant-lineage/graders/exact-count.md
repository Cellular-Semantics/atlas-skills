---
type: regex
target: { source: file, path: picks.json }
pattern: "\"cell_type\"\\s*:\\s*\\[\\s*\"[^\"]*\"\\s*,\\s*\"[^\"]*\"\\s*\\]"
---

`picks.cell_type` holds exactly 2 column(s), as curated: `Cell.class`, `Cell.group`. An extra pick fails this.
