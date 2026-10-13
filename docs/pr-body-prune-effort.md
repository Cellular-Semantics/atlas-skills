Prunes effort on easy records, and makes grain choices evidence-based rather than arbitrary.

Follows the brief's note that two reviewed records drew the comment *"excessive effort for simple mapping"*.

## The short path

A **one-annotation** record — everything it says about the target reducing to a single name, with nothing left over to discriminate — stops after the exact probe when that probe returned one term on label or exact synonym, the string was not flagged ambiguous in Prepare, and the definition fits.

Measured on the 49 reviewed HDCA records, Opus both sides:

| | before | after |
|---|---|---|
| records settled in one move | 5 / 49 | **16 / 49** |
| mean moves | 2.78 | 2.27 |
| cost per record | $0.58 | **$0.24** |

`U129` `dorsal root ganglion` — the record that prompted this — went from three probes and two `term` calls to one call, same answer. `U030` kept both its moves, correctly: it has coarse fields to check against, so it is not one-annotation.

**The guard is the string, not the term.** `cortex` returns exactly one exact hit on the label, and `UBERON:0001851` is defined "Outermost layer of an organ". What stops it is that Prepare flags `cortex` as a short common ambiguous word before any query runs. An earlier draft guarded this with a grouping-class screen whose second tell needs the parent class — unobtainable from a probe, so the condition could not be met without the `term` call the short path exists to avoid.

## Grain

`oq term` now computes specificity itself: information content over `subClassOf` and `part_of`, over terms the queried ontology defines. Ubergraph's own measures do not work here — `normalizedInformationContent` is whole-store, so a Uberon term's score depends on how much CL or GO hangs off it, and `normalizedSubClassInformationContent` saturates, putting `liver` and `abdomen` both at 100.

It also reports `subsumed_by` and warns when no candidate subsumes another, because the score ranks only along one path. `thoracic wall` scores 92.8 against `rib` 55.5 — Uberon defines two thoracic walls and seventy-two ribs — and the record still says rib.

`subClassOf` + `part_of` is carried by essentially every OBO ontology, so this generalises beyond Uberon.

## Batching

A sweep over 50 records at batch sizes 5/10/15/20/25, Sonnet, found cost flattening after 10 ($0.148 → $0.090 → $0.076) with no quality signal: new disagreements were 3, 3, 4, 3 across a 2.5× range, and no position effect within batches. Batch 15 is the floor.

## What this does not fix

Four reproductive-tract records move in lockstep — consistent within a run, shifting together between runs. The agent settles on a grain convention per session rather than wavering per record. That is a convention the corpus needs to state, not something the skill can infer.

## Corrections made during the work

`run-batch.py` detected `oq` calls by a literal lowercase `oq `, which only matched the first command of a run; on that basis I twice reported `term` was never called and the grain rule unreachable. Fixed: 19 of 74 calls are `term`. Transcripts were also named from the first unit and batch size, so concurrent repeats interleaved into one file.

The `U063` eval case asserted `rib` and failed `thoracic wall`, written from a score rather than from what the record denotes. Reframed to accept either with the other named.

Requires onto-query ≥ 0.4.0 (`pkg-onto-query--v0.4.0`), tagged.
