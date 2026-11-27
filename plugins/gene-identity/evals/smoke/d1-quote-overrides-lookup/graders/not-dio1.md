---
type: regex
target: { source: file, path: result.gene-records.json }
pattern: "\"ncbi_gene_id\"\\s*:\\s*\"NCBIGene:13370\""
match: not_contains
---

The gene is not Dio1 (NCBIGene:13370), the lookup's single match for the string `D1`: one claimant is not the gene the source means. Naming Dio1 in the rationale is fine.
