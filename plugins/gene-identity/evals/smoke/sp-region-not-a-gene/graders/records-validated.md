---
type: tool_used
tool: Bash
input_match: '"command"\s*:\s*"(?:[^"\\]|\\.)*?\bgene-id\b(?:[^"\\]|\\.)*?\b(?:validate|check)\b'
---

SKILL.md "The record": a records file is checked with `gene-id validate`, or `gene-id check` (which validates first), before it is reported done.
