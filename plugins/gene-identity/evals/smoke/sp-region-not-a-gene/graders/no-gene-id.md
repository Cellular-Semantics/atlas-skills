---
type: regex
target: { source: file, path: result.gene-records.json }
pattern: "\"ncbi_gene_id\"\\s*:\\s*\"NCBIGene"
match: not_contains
---

No gene: not Tac1 (substance P) or any other claimant of `SP`.
