Prunes wasted effort on easy records and makes grain choices evidence-based.

**Short path.** A record whose whole content reduces to one name stops after the exact probe, when that probe returned a single term on label or exact synonym, Prepare did not flag the string ambiguous, and the definition fits. On the 49 reviewed HDCA records (Opus both sides): records settled in one move **5 → 16**, cost per record **$0.58 → $0.24**. `dorsal root ganglion` went from three probes and two `term` calls to one.

The guard is the string, not the term — `cortex` returns one clean-looking hit and `UBERON:0001851` is "Outermost layer of an organ"; Prepare flags `cortex` as ambiguous before any query runs.

**Grain.** `oq term` now reports specificity (IC over `subClassOf` + `part_of`, scoped to the queried ontology) and `subsumed_by`. The score decides only where one candidate subsumes another; otherwise it is silent and the command says so. `thoracic wall` scores 92.8 against `rib` 55.5 and the record still says rib.

**Batching.** Cost per record flattens after batch 10 ($0.148 → $0.076 at 15), with no quality signal across 5–25 and no position effect inside batches.

**Not fixed, deliberately.** Four reproductive-tract records shift in lockstep between runs — the agent picks a grain convention per session. That is a convention the corpus needs to state, not something the skill can infer.

Requires `onto-query` ≥ 0.4.0 (tagged). Two measurement bugs found and fixed mid-work are described in `docs/pr-body-prune-effort.md`.
