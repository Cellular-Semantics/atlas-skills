---
tags: [smoke, gene-id-curation, dopamine]
runs: 1
max_turns: 30
timeout_seconds: 600
allowed_tools: [Read, Glob, Grep, Skill, TodoWrite, Write, Bash]
---

Use the gene-id-curation skill on this name:

- name: `D1`
- taxon: `NCBITaxon:10090`
- title: Dopaminoceptive D1 and D2 neurons in ventral hippocampus arbitrate approach and avoidance in anxiety
- evidence: "We here study dopaminoceptive neurons in mouse ventral hippocampus (vHipp), molecularly distinguished by their expression of dopamine D1 or D2 receptors" (PMID:37546856)

Which NCBI gene does the name refer to? Write the record to `result.gene-records.json` in the current directory, not a subdirectory, and tell me the outcome.
