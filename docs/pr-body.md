Reviews rungs 0 and 1 of the mapping ladder, as briefed, and ends up replacing the ladder.

## The library first

`onto-query` 0.2.0 → 0.3.0 (`pkg-onto-query--v0.3.0`). The six predicate names were an argparse gate, so every other RO predicate was unreachable. They are now an alias table: a CURIE passes through, a bare word must still be a known alias so a typo fails loudly. `common-ancestors` deliberately keeps the curated set — it ranks by information content, and IC is comparable between rows only because every row came from the same traversal.

Widening `-p` alone would not have helped: `term` keyed its relations by predicate *label*, so a caller reading "connected to" had nothing to pass on. Fixing that exposed two `to_curie` bugs — `rdfs:subClassOf` returned as a bare IRI, and Uberon's `core#extends_fibers_into` split on its first underscore into `core#extends:fibers_into`, which is not a CURIE and close enough to one to be believed.

`neighbours` now reads OLS4 v2 for outgoing relations. v1 dedupes edges by source and target, so a term asserting two predicates against one target silently loses one — `EHDAA2:0001570` pronephros is CS09–CS09 and reads through v1 as CS09 with no end bound. Incoming has no v2 equivalent and still carries that limitation, now reported rather than hidden.

New: `cohort --under` (region-scoped survey over subClassOf *and* part_of) and `cohort --text-contains` (label **or** synonym). The second matters more than it looks: `spine` under the vertebral column gives 10 terms by label with none of them regional, against 16 by label-or-synonym including the cervical, thoracic and lumbar regions — all reachable only through a synonym, and exactly the terms a record saying "spine" wants. Plus `lexical --compact` and `term` over a shortlist.

Retires gaps 1, 2, 3 and the filter half of 4.

## The skill

Prepare → Find → Prune → Confirm → Judge, replacing the ladder. Two exit rules removed for being wrong rather than verbose: "exactly one term" (`cortex` returns exactly one, and it is a grouping class defined "Outermost layer of an organ") and "no more than about five" (no basis, nothing enforced it, and batching removed the cost it capped).

717 lines → 404, with every measured claim preserved; the long form is kept at `docs/map-to-ontology-long-form.md`, outside the plugin.

Model and batch size are the caller's: a skill cannot select a model, and an agent-per-record would give back the batching win.

## Evidence

70 real HDCA tissue descriptions, run against the installed plugin in isolated temp directories. Results in `docs/hdca-fetal-tissue/` (see its README).

Terse+batched matched verbose+single on 12/12 identical inputs at half the cost. A smaller model agreed on 38/49 but named a mean 1.5 rejected rivals against 4.5, and none at all on 19 — those fail the skill's own exit test whatever term they reached.

## Eval harness

`check.py` scored a `rung` integer, which has no referent now. It scores which **moves** were made and which answered, against a closed vocabulary in `moves.py` kept in step with the Stage 2 headings. 12 cases remapped, 3 added for behaviour this branch introduced, and `test_check.py` pins the scorer itself.

## Not done

Gap 4's `--depth`. The 21 slice-50 records Opus never ran, so the paired comparison over-weights brain and reproductive-tract studies. New Prepare behaviour (free text, bare study name, mixed granularity) has no eval case yet.
