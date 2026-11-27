---
tags: [smoke, gene-id-curation, region]
runs: 1
max_turns: 30
timeout_seconds: 600
allowed_tools: [Read, Glob, Grep, Skill, TodoWrite, Write, Bash]
---

Use the gene-id-curation skill on this name:

- name: `SP`
- taxon: `NCBITaxon:10090`
- title: Single-nucleus profiling reveals a core disease signature and cell type-specific vulnerabilities in early Rett syndrome
- evidence: "We confirmed that Chrm2 colocalizes with Gad2 and labels a sparse number of INs located mainly within the SO and SP layers of CA1-CA3 (Fig. 6, C to E)." (PMID:42268975)

Which NCBI gene does the name refer to? Write the record to `result.gene-records.json` in the current directory, not a subdirectory, and tell me the outcome.
