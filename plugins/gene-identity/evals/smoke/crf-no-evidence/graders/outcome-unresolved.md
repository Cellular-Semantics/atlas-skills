---
type: regex
target: { source: file, path: result.gene-records.json }
pattern: "\"outcome\"\\s*:\\s*\"UNRESOLVED\""
---

Two genes claim CRF (Crh, C1ql1) and nothing in the input says which: no field convention can be applied without a field, so the name is left unresolved.
