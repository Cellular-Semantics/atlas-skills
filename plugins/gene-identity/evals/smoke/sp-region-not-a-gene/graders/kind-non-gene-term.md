---
type: regex
target: { source: file, path: result.gene-records.json }
pattern: "\"kind\"\\s*:\\s*\"NON_GENE_TERM\""
---

A region that looks like a gene name is `NON_GENE_TERM`.
