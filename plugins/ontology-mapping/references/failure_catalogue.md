# What went wrong, and which rule exists because of it

Every entry here happened while mapping 27 prenatal subatlases by hand. The
rules in `ontomap` are shaped by this list; read it before relaxing one.

## Retrieval

**Relevance rank is not identity.** `upper reproductive tract` → `lateral nasal
gland` (a rodent gland). `mid vertebrae` → `longissimus cervicis muscle` (its
*definition* mentions vertebrae). `internal organs` → `mucosa of
pharyngotympanic tube`. All from taking rank 1.
→ *Lexical search produces candidates only. No rung assigns on a score.*

**`exact=true` is not an exact-match filter.** In OLS it returns the same
relevance-ranked list unless `queryFields` is pinned. A rule that looked exact
silently degraded to "top hit", which is how `skin` (202 samples) became `pedal
digit skin`.
→ *Exact matching runs against a local label/synonym table, not a search API.*

**A unique exact synonym can still be the wrong term.** `skin` is a *unique
exact synonym* of `zone of skin`, a grouping class; `skin of body` carries it
only as a related synonym. Uniqueness alone assigns the wrong term with no
hesitation.
→ *Grouping classes are removed before the synonym rung, and `skin` falls
through to judgement.*

**Namespace is not provenance.** Querying `ontology=uberon` also returns the CL
and GO terms UBERON imports: they carry `ontology_name="uberon"` and a `CL:` id.
`Thymic stroma` → `CL:4030001 stromal cell of thymus`, a cell type in a tissue
field.
→ *Filter on the IRI. `PREFIX_EXPECTED` as a gate.*

**Multi-species ontologies return other species' anatomy.** `embryo head` →
`insect embryonic head segment`, with the correct term at rank 2.
→ *Refusal catches it today; UBERON's taxon constraints will make it impossible.*

## Structure

**Deepest is not most usable.** `uterus, cervix, vagina` has `subdivision of
oviduct` as its literally deepest common ancestor — and it ties with `oviduct`
on information content, so a specificity ranking does not fix it either.
→ *Roll up by `part_of` closure, which drops classification-only ancestors, and
demote grouping classes at any depth.*

**Classification is not containment.** Liver and thymus are both endocrine
glands. That is not a place a sample came from.
→ *`part_of` only for roll-up, and organ systems are refused as sampled sites.*

**A plausible exemplar may not be asserted.** `viscus` was proposed for "internal
organs" with liver as exemplar; UBERON asserts pancreas under viscus, not liver.
The term was right and the exemplar wrong.
→ *`BROAD_IS_ANCESTOR` queries it rather than assuming.*

**Absence of lexical evidence is not evidence of absence.** A first pass
concluded "45 of 63 organs have no developmental variant". Relation traversal
found precursors for most, under names sharing no words with the organ.
→ *Precursors come from `develops_from` and from EHDAA2, not from label patterns.*

**Per-relation REST endpoints may not be typed.** OLS's `/part_of` and
`/develops_from` return the same merged set whichever is asked.
→ *Relations come from SPARQL, where the predicate is the query.*

**Per-term crawling does not scale.** 69 organs at depth 2 took 5.5 minutes one
request per term; one relation-graph query returns the whole set in seconds.
→ *Fetch the relation once, walk it locally, use the non-redundant graph.*

**The axioms may be in a different graph than you asked.** Taxon constraints and
existence-window edges both return **zero rows** from Ubergraph's `ontology`
graph and thousands from `nonredundant`. Zero rows reads as "the ontology does
not say this". This mistake was made twice, the second time by someone who had
already written the warning down.
→ *Every method names its graph. None defaults. A live test asserts it.*

## Values

**Unit conventions differ invisibly.** Gestational age counts from the last
menstrual period, post-fertilization from conception — two weeks apart, and
HsapDv week terms are post-fertilization.
→ *Shift, flag every shifted row, and treat the frame as a per-study question.*

**Units live in a sibling column.** Bare ages (`14`) with `Unit[time unit]`
elsewhere. ~60 distinct values were stranded until it was folded in.
→ *`unit_column` in the config. A bare number is refused, not guessed at.*

**A mixed value maps to no term, which makes guards useless.** `sex = 'female,
male'` correctly maps to nothing. A blocker reading the *mapped* field sees an
empty value for exactly the pooled rows needing a block; 12 rows were wrongly
specialised.
→ *`sex_mixed` is a flag on the raw text. Absent and ambiguous are different
states everywhere.*

## Measurement

**Archive exports contain samples the atlas never ingested.** A correctly-mapped
`colon` in a thymus study's accession scored as an error.
→ *Scope filter from the first step; in- and out-of-scope reported separately.*

**The gold set only covers the paths it exercises.** 15/15 on stage and 8/8 on
tissue, *while* `skin` was mapped to `pedal digit skin`: every gold tissue string
hit an exact label, so the fuzzy path was never tested. A human reading the table
found it.
→ *Per-rule accuracy; untested paths named as unevaluated; no bare aggregate.*

**Gold values may be truncated by your own tooling.** Gold ids read from reports
that cut category lists at 5 values, so most comparisons were partial.
→ *State the gold set's completeness; "not in gold" is not "wrong".*
