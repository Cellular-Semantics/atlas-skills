---
type: regex
target: { source: file, path: result.gene-records.json }
pattern: "\"ncbi_gene_id\"\\s*:\\s*\"NCBIGene"
match: not_contains
---

No single member is picked: the lookup's claimants (Camk2a, Camk2b, Camk2d) are all family members.
