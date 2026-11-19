---
type: tool_used
tool: Bash
input_match: '"command"\s*:\s*"(?:[^"\\]|\\.)*?\b(?:curl|wget)\b'
min: 0
max: 0
---

No `curl` or `wget`: the skill's own commands read obs over range requests, and an agent only reaches for curl when they fail.
