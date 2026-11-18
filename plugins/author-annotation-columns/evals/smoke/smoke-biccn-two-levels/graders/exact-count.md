---
type: regex
target: { source: file, path: picks.json }
pattern: "\"cell_type\"\\s*:\\s*\\[\\s*\"[^\"]*\"\\s*,\\s*\"[^\"]*\"\\s*\\]"
---

`picks.cell_type` holds exactly 2 column(s), as curated: `BICCN_class_label`, `BICCN_cluster_label`. An extra pick fails this.
