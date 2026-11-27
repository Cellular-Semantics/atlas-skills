---
tags: [smoke, gene-id-curation, antibody]
runs: 1
max_turns: 30
timeout_seconds: 600
allowed_tools: [Read, Glob, Grep, Skill, TodoWrite, Write, Bash]
---

Use the gene-id-curation skill on this name:

- name: `NeuN`
- taxon: `NCBITaxon:10090`
- evidence: "Sections were immunostained for NeuN to label neuronal nuclei."

Which NCBI gene does the name refer to? Write the record to `result.gene-records.json` in the current directory, not a subdirectory, and tell me the outcome.
