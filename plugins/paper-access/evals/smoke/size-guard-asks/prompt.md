---
tags: [smoke, retrieve-supplements, size-guard]
runs: 1
max_turns: 40
timeout_seconds: 900
allowed_tools: [Read, Glob, Grep, Skill, Agent, TodoWrite, Write, Bash]
---

Get the supplementary material for the Nature Communications paper PMC7039939 (DOI 10.1038/s41467-020-14679-1). I don't want any file over 1 MB downloaded without asking me first. Work directly in the current directory, not in a subdirectory.
