"""Help text for the ``oq`` CLI.

Kept out of cli.py so the command wiring stays readable. Everything here is
prose: descriptions, output shapes, worked examples and the gotchas that cost
real time to find.
"""

from __future__ import annotations

MAIN = """\
Query primitives over OLS4 and Ubergraph for mapping free text to ontology terms.

Every command returns annotated evidence. Nothing here scores, thresholds,
ranks by relevance, or picks a winner -- that judgement belongs to the caller,
where it can be seen and argued with. If you find yourself wanting a "best
match" field, the decision you want to make should be made somewhere you can
write down a reason for it.

Backends, and which does what:

  OLS4        lexical candidate generation. Tokenised and stemmed, covers
              labels, every synonym scope and definitions, and reaches
              ontologies absent from Ubergraph. Latency is erratic
              (0.96-28s measured on identical calls).
  Ubergraph   everything logical: common ancestors, information content,
              closure, relations, term axioms. ~45 OBO ontologies.
"""

MAIN_EPILOG = """\
output
  One JSON object per invocation:

    {
      "tool":     "onto-query",
      "version":  "0.1.0",
      "command":  "lexical",
      "backend":  "ols4" | "ubergraph",
      "params":   { ... what was actually asked ... },
      "warnings": [ "..." ],        <- read these; they are not decoration
      "result":   { ... }           <- shape depends on the command
    }

  Errors print the same envelope with an "error" key instead of "result".

exit codes
  0   fine
  2   bad input (unknown predicate, seed cap exceeded, ontology not in
      Ubergraph, ...)
  3   transport failure after retries

orientation
  oq ontologies                       what Ubergraph holds
  oq lexical -q skin -o uberon        lexical probes against OLS4
  oq <command> --help                 options, result shape and examples

  Output is JSON; each command's help ends with jq recipes.

further reading
  docs/README.md           the design, and the escalation ladder this serves
  docs/capability-note.md  what each backend actually does, measured
"""

LEXICAL = """\
Lexical probes against OLS4 for one or more query strings.

Three probes, run independently and merged. A hit records every probe that
found it, so the probes are comparable rather than collapsed.

  exact        queryFields=label,synonym with exact=true. Whole-string match
               against the label or any synonym, case-insensitive. Cheap, and
               the only probe whose matched fields can be reported exactly.
  stemmed      queryFields=label,synonym. Tokenised and stemmed -- "muscles"
               and "muscle" return the same 768 hits in uberon. Definitions
               excluded. High recall.
  definition   the default OLS4 search minus the stemmed set: terms matching
               only in their definition text. Roughly 40% of a result set
               (160 of 282 for "skin", 523 of 1291 for "muscle").
"""

LEXICAL_EPILOG = """\
result
  A list, one entry per query string:

    { "query": "skin",
      "ontology": "uberon",
      "search_config": { ... see below ... },
      "probes": {
        "exact":   {"query_fields": "label,synonym", "exact": true,
                    "num_found": 4, "returned": 4, "truncated": false},
        "stemmed": {"query_fields": "label,synonym", "exact": false,
                    "num_found": 121, "returned": 121, "truncated": false} },
      "total": 121,
      "hits": [
        { "curie": "UBERON:0000014",
          "label": "zone of skin",
          "definition": "...",
          "synonyms": {"exact": [...], "broad": [...],
                       "narrow": [...], "related": [...]},
          "found_by": {
            "exact":   {"rank": 1, "matched_fields": ["exact_synonym"]},
            "stemmed": {"rank": 22} } } ] }

matched_fields
  Reported for the exact probe only, where the match is whole-string and the
  comparison is therefore reliable:

    curie            label             matched_fields
    UBERON:0000014   zone of skin      exact_synonym
    UBERON:0002097   skin of body      related_synonym
    UBERON:0001003   skin epidermis    broad_synonym
    UBERON:0002199   integument        related_synonym

  A broad synonym matching your text means the term is narrower than your
  text; a narrow synonym matching means it is broader. Different mistakes.

  Not attempted for the stemmed probe. Stemming and tokenisation make a
  client-side reconstruction wrong more often than right -- "muscles" matches
  "muscle organ" at the backend but matches no field verbatim -- and OLS4
  offers no highlighting to ask instead.

rank
  Position within that probe's results, which is Solr's relevance order. OLS4
  exposes no score (not in the document, not via fl=score or
  fieldList=score), so rank is the only trace of the scoring there is. Take it
  loosely:

    reliable    it segregates match channels completely. Definition-only hits
                rank strictly below every lexical hit -- 111-282 of 282 for
                "skin", 665-1291 of 1291 for "muscle", none in either top 100.
    unreliable  within the lexical band. "skin of body" ranks 46th and
                "muscle organ" 360th, which is why the probes are separated
                explicitly rather than left to the ordering.

search_config
  What OLS4 treats as label, synonym and definition for this ontology, from
  its own config. It is not uniform: most OBO ontologies declare nothing and
  take OLS4's defaults (uses_ols4_defaults: true), but EFO declares
  efo:alternative_term alongside hasExactSynonym -- so "a synonym match" means
  something different there, and you get a warning saying so.

examples
  # exact probe
  oq lexical -q skin -o uberon --probes exact

  # several candidate names in one invocation
  oq lexical -o uberon --probes exact \\
     -q "reproductive tract" -q "reproductive system" -q "genital tract"

  # how big is each band?
  oq lexical -q muscle -o uberon --probes exact,stemmed,definition \\
    | jq '.result[0].probes | map_values({num_found, returned})'

  # exact hits with the field that matched
  oq lexical -q skin -o uberon --probes exact | jq -r '
    .result[0].hits[]
    | [.curie, .label, (.found_by.exact.matched_fields | join(","))] | @tsv'

  # where the stemmed probe put them
  oq lexical -q skin -o uberon --probes stemmed | jq -r '
    .result[0].hits[] | [.found_by.stemmed.rank, .curie, .label] | @tsv' | head

notes
  A zero result on a multi-token query is informative rather than a failure:
  "full reproductive tract" returns nothing because no term carries all three
  tokens. Drop the weakest token and try again.

  Hundreds of hits is normal for a general word and is recall working
  correctly. Reduce with common-ancestors over a seed set you have chosen,
  rather than by reading down the list.

  The default search (not used by any probe here on its own) also matches
  short_form and obo_id, so an identifier can be looked up with it. It does
  not match xrefs.
"""

COMMON_ANCESTORS = """\
Subsumers shared by a set of seed terms, restricted to one target ontology.

Each subsumer is annotated with how many seeds it covers, which seeds it
misses, and Ubergraph's precomputed normalized information content. Results
are ordered by coverage then IC, as an ordering of evidence -- no winner is
chosen and no coverage threshold is applied.

The seed set does the work, and choosing it is yours. Seeds that genuinely
co-annotate one thing make the common ancestor the answer. Seeds that merely
share a word make this a discovery move, and only after you have split them
by sense: all 75 Uberon "muscl*" terms together yield nothing better than
"anatomical structure", because the set mixes muscle-as-organ with
muscle-layer-of-a-wall.
"""

COMMON_ANCESTORS_EPILOG = """\
result
    { "seeds": ["UBERON:0000964", "UBERON:0001811"],
      "target_ontology": "uberon",
      "predicates": ["subClassOf", "part_of"],
      "subsumers": [
        { "curie": "UBERON:0010409",
          "labels": ["ocular surface region"],   <- a list; some terms have two
          "ic": 57.29,
          "covers": 2,
          "of_seeds": 2,
          "missing_seeds": [],
          "is_seed": false } ] }

reading the IC column
  Three shapes, and they mean different things:

    one clear winner   cornea + conjunctiva -> ocular surface region at 57.29,
                       next at 44.61. Take it.
    a band, a cliff    glycolysis + TCA cycle -> four candidates between 56.75
                       and 60.34, then a 39-point drop. The band is the answer;
                       adjudicate it, do not let the ordering decide.
    a low ceiling      cornea + femur -> nothing above 33.75, on a cross-cutting
                       grouping class. These terms share no meaningful ancestor.

  IC is comparable within one result set only. The scale is not zero-based at
  the root (GO:0008150 scores 15.54, UBERON:0001062 scores 1.33), so never
  compare scores across ontologies or across queries.

missing_seeds and is_seed
  Coverage is reported, never filtered, because a hard 100% filter hides what
  you need. For the 82 skin-zone seeds, "zone of skin" has the highest IC of
  anything returned and covers 81 of them -- and the seed it misses is
  "skin of body", which should not have been in the partition. A high-scoring
  near miss usually means your seed set is wrong, not that the graph disagrees.
  The CLI warns when that pattern appears.

  is_seed marks a seed appearing among its own ancestors. The closure is
  reflexive, so this is expected; it is flagged rather than dropped because if
  one seed subsumes all the others, it is a legitimate answer.

examples
  # the canonical case: a sample annotated "Cornea/Conjunctiva"
  oq common-ancestors -s UBERON:0000964 -s UBERON:0001811 -t uberon

  # what the same query loses without part_of (it warns, too)
  oq common-ancestors -s UBERON:0000964 -s UBERON:0001811 -t uberon \\
     --predicates subClassOf

  # a band rather than a winner, in GO
  oq common-ancestors -s GO:0006096 -s GO:0006099 -t go

  # seeds and target ontology are independent: what structure are these
  # cell types all in?
  oq common-ancestors -s CL:0000604 -s CL:0000573 -s CL:0000636 -t uberon

  # full-coverage, non-seed subsumers as a table
  oq common-ancestors -s UBERON:0000964 -s UBERON:0001811 -t uberon | jq -r '
    .result.subsumers[]
    | select(.missing_seeds == [] and .is_seed == false)
    | [.ic, .curie, (.labels | join("/"))] | @tsv'

  # near misses worth a look, with the seeds they fail to cover
  oq common-ancestors ... | jq -r '
    .result.subsumers[]
    | select(.missing_seeds != [] and .is_seed == false)
    | [.ic, .curie, (.labels|join("/")), (.missing_seeds|join(","))] | @tsv'

notes
  part_of is in the default predicate set and dropping it is usually a
  mistake: cornea and conjunctiva are *parts of* the ocular surface region,
  not subclasses of it, and over subClassOf alone the right answer silently
  disappears. The same holds in GO.

  Seeds are capped at 300. Measured: 82 seeds return in 0.9s, 718 time out.
  Over the cap this errors rather than hanging -- partition by sense first.
"""

RELATIONS = """\
Terms standing in a named relation to one term, in either direction.

Runs over Ubergraph's inference closure, where every predicate except
subClassOf is shorthand for an existential restriction. Works across
ontologies: part_of retina returns 55 CL terms.
"""

RELATIONS_EPILOG = """\
result
    { "anchor": "UBERON:0000966",
      "predicate": "part_of",
      "direction": "in",
      "target_ontology": "cl",
      "total": 55,
      "terms": [ { "curie": "CL:0000573", "labels": ["retinal cone cell"] } ] }

direction
  in    what points at the anchor -- what is part_of this region
  out   what the anchor points at -- what this term is part_of

examples
  # what cell types are recorded in the retina
  oq relations UBERON:0000966 -p part_of -d in -t cl

  # what is the cornea part of
  oq relations UBERON:0000964 -p part_of -d out -t uberon

  # just the labels
  oq relations UBERON:0000966 -p part_of -d in -t cl \\
    | jq -r '.result.terms[] | .labels[0]'

notes
  Use part_of for cells in a region. located_in (RO:0001025) returns nothing
  for CL->Uberon in practice. overlaps is worth trying as a looser
  alternative -- Ubergraph's own example query for cells by location uses it.

  Without -t, subsumers from every ontology in the store come back.
"""

TERM = """\
Annotations and relations for one term.

Literal annotations (definition, synonyms, xrefs) come from the per-ontology
asserted graph. Relations come from the nonredundant graph, with the labels of
their objects resolved across ontologies.
"""

TERM_EPILOG = """\
result
    { "curie": "UBERON:0010409",
      "ontology": "uberon",
      "annotations": {"IAO_0000115": ["The integrated unit ..."],
                      "hasExactSynonym": ["ocular surface", "eye surface"],
                      "hasDbXref": ["EMAPA:35336", "MA:0002486"]},
      "relations": {"part of": [{"curie": "UBERON:0000019",
                                 "labels": ["camera-type eye"]}],
                    "in taxon": [{"curie": "NCBITaxon:7742",
                                  "labels": ["Vertebrata <vertebrates>"]}]} }

examples
  oq term UBERON:0010409 -o uberon

  # taxon constraints, for checking a candidate against a species field
  oq term UBERON:0010409 -o uberon | jq '.result.relations["in taxon"]'

  # the definition on its own
  oq term UBERON:0010409 -o uberon | jq -r '.result.annotations.IAO_0000115[0]'

notes
  The nonredundant graph is pruned but not free of closure noise --
  UBERON:0010409 carries fifteen "existence starts during or after" edges
  there. A warning says so on every call; treat the relations as inferred
  rather than asserted.

  Computed taxon constraints are evidence to read, not a gate to apply
  automatically. They can be wrong.
"""

COHORT = """\
Survey an ontology's labels, to read a naming convention off real terms
instead of guessing at it.

Exactly one of --sibling-of or --label-contains.
"""

COHORT_EPILOG = """\
result
    { "ontology": "hsapdv",
      "sibling_of": null,
      "label_contains": "week",
      "total": 30,
      "truncated": false,
      "terms": [ { "curie": "HsapDv:0000046",
                   "labels": ["9th week post-fertilization stage"] } ] }

examples
  # how does this ontology word ages in weeks?
  oq cohort -o hsapdv --label-contains week | jq -r '.result.terms[].labels[0]'
  # -> 9th week post-fertilization stage
  #    10th week post-fertilization stage   ... and so on

  # what sits alongside a term you are confident about
  oq cohort -o uberon --sibling-of UBERON:0006073

notes
  This is the move for anything with a number, unit or abbreviation in it.
  Human developmental stage terms carry *no synonyms at all*, so no amount of
  trying "12 pcw", "wk 12" or "12 weeks PCF" will ever hit one -- the only
  route is to learn the convention and construct the string.

  --label-contains is a substring match over asserted labels in one ontology,
  so it is cheap. Check "truncated" and raise --limit if it is true.
"""

ONTOLOGIES = """\
List the named graphs in Ubergraph, i.e. which ontologies the graph commands
can reach.
"""

ONTOLOGIES_EPILOG = """\
examples
  oq ontologies | jq -r '.result.named_graphs[]'

notes
  Two kinds of graph come back: one per source ontology (uberon-base.owl,
  cl-base.owl, hsapdv.owl, ...) holding asserted axioms, and the global
  reasoning graphs under reasoner.renci.org holding inferred relations across
  all of them.

  An ontology absent from this list can still be searched with `oq lexical`
  via OLS4, but no graph command will work on it. Say so in any report rather
  than quietly skipping the step.
"""


RELEASE = """\
Which release of an ontology OLS4 and Ubergraph are each serving, and whether
they agree. Run this before trusting an answer assembled from both.
"""

RELEASE_EPILOG = """\
examples
  oq release -o hsapdv
  oq release -o hsapdv --expect 2025-01-23
  oq release -o uberon --refresh

what it compares
  OLS4 reports `config.version` and `config.versionIri` for the copy it
  loaded. Ubergraph holds the ontology header in the per-ontology asserted
  graph, so owl:versionInfo and owl:versionIRI come straight from the release
  it ingested. Where an ontology asserts no version, the date is taken from
  the version IRI.

  The two backends reload on unrelated schedules. When they disagree, an
  answer built from both is built from two different ontologies and nothing
  in either response says so. That is the case this command exists to catch:
  read `agree`, and read the warnings.

--expect
  Assert the release a written reference assumes. `matches_expected` is false
  if either backend has moved on, which is the signal to re-derive whatever
  the reference recorded rather than trusting it.

caching
  The result is cached by date, per ontology, so repeated runs on the same day
  cost nothing. `from_cache` says whether the network was touched, and
  `cache_age_days` how old the entry is. --refresh forces a new check;
  --max-age-days changes the window.

  The cache is a per-user state file -- %LOCALAPPDATA% on Windows,
  $XDG_STATE_HOME (default ~/.local/state) elsewhere -- under onto-query/.
  Set $ONTO_QUERY_CACHE or pass --cache to put it somewhere else. It is state,
  not a document: deleting it costs two requests. `cache` in the result says
  which file was used.

  When a cached entry is replaced, a `previous` block reports what moved since
  the last check. A release that changed under you is worth knowing about.
"""


XREFS = """\
Database cross-references for a term, resolved where possible.

In OBO ontologies an xref is a plain annotation -- oio:hasDbXref "MA:0002486"
-- a literal string, not a link and not a logical assertion. Two things are
done with it here, and they are kept apart because they carry different weight:

  xrefs      the literals, joined back to real classes where Ubergraph holds
             the target ontology, and enriched with a resolvable URL from
             OLS4's v2 API. A resolved xref gives you the target's label and
             which ontology defines it.
  mappings   SKOS assertions (exactMatch, closeMatch, ...) the source ontology
             actually made. Most OBO ontologies have none; MONDO carries
             plenty. These are claims, where xrefs are only pointers.
"""

XREFS_EPILOG = """\
result
    { "curie": "UBERON:0010409",
      "xrefs": [
        { "value": "MA:0002486",
          "resolved": {"curie": "MA:0002486",
                       "defined_by": "http://purl.obolibrary.org/obo/ma.owl"},
          "labels": ["eye surface"],
          "url": "http://www.informatics.jax.org/searches/AMA.cgi?id=MA:0002486",
          "registry": "https://raw.githubusercontent.com/geneontology/go-site/..." } ],
      "unresolved": [],
      "mappings": {"exactMatch": [{"curie": "...", "label": "..."}]} }

where each piece comes from
  resolved + labels   a SPARQL join in Ubergraph. The xref literal is turned
                      into an IRI and looked up; since Ubergraph holds ~45 OBO
                      ontologies, targets in EMAPA, MA, ZFA, FBbt and so on
                      resolve. One query, no extra round trip.
  url + registry      OLS4 v2's linkedEntities, which is what the OLS web
                      front end uses to make an xref clickable. It names the
                      registry that supplied the URL -- GO's db-xrefs.yaml or
                      bioregistry. Costs one extra request; --no-urls skips it.
  mappings            asserted SKOS triples in Ubergraph's ontology graph.

examples
  oq xrefs UBERON:0010409 -o uberon

  # xrefs as a table
  oq xrefs UBERON:0010409 -o uberon | jq -r '
    .result.xrefs[] | [.value, (.labels|join("/")), (.url // "-")] | @tsv'

  # a term with real SKOS mappings rather than bare xrefs
  oq xrefs MONDO:0007739 -o mondo | jq '.result.mappings | map_values(length)'

  # skip the URL lookup
  oq xrefs UBERON:0010409 -o uberon --no-urls

notes
  An xref that does not resolve is reported in "unresolved" and warned about.
  It usually means the target ontology is not in Ubergraph (a non-OBO database,
  a publication, a retired identifier), not that the xref is wrong.

  Do not read an xref as equivalence. It is an annotation saying "related to
  this identifier somewhere else", and ontologies use it loosely. Where the
  source ontology meant equivalence it generally said so with SKOS, which is
  why mappings are reported separately and a term with none is flagged.
"""


CROSSWALK = """\
Find terms that cross-reference an identifier -- the reverse of `xrefs`.

This is how to reach an ontology Ubergraph does not hold. EHDAA2 is not in the
store, but Uberon cross-references it extensively, so an EHDAA2 identifier
still resolves to a Uberon term.

  oq lexical -q liver -o ehdaa2   ->  EHDAA2:0000997   (OLS4: 287 ontologies)
  oq crosswalk EHDAA2:0000997     ->  UBERON:0002107   (Ubergraph: ~45)

So the division of labour is not "Ubergraph for queries, OLS4 for links". It
is: OLS4 reaches every ontology lexically; Ubergraph reasons over the ~45 it
holds; and xrefs bridge between them in both directions.
"""

CROSSWALK_EPILOG = """\
result
    { "xref": "EHDAA2:0000997",
      "target_ontology": "uberon",
      "total": 1,
      "terms": [ { "curie": "UBERON:0002107",
                   "labels": ["liver"],
                   "defined_by": "http://purl.obolibrary.org/obo/uberon.owl" } ] }

examples
  # an ontology Ubergraph does not hold, bridged into one it does
  oq crosswalk EHDAA2:0000997 -t uberon

  # unrestricted: every ontology in the store that cites this identifier
  oq crosswalk EMAPA:16846
  # -> MA:0000358 (liver), UBERON:0002107 (liver)

  # round trip, to see what else Uberon says the same thing as
  oq xrefs UBERON:0002107 -o uberon --no-urls | jq -r '.result.xrefs[].value'

notes
  Zero hits means no ontology in Ubergraph cites that identifier. It does not
  mean the term has no equivalent -- the bridge only exists where somebody
  wrote the xref down.

  Several terms can cite the same identifier, as MA and Uberon both do for
  EMAPA:16846. That is information about how the two ontologies align, not a
  conflict to resolve.

  An xref is an annotation, not an assertion of equivalence. Treat a crosswalk
  hit as a strong lead to adjudicate, not as a mapping.
"""


NEIGHBOURS = """\
The one-hop neighbourhood of a term, from OLS4's term graph.

Asserted direct relations in both directions, with predicate and node labels
already resolved, in a single request.

This is how to get relations for an ontology Ubergraph does not hold. EHDAA2
is OLS4-only, and its link into HsapDv is visible nowhere else:

  EHDAA2:0000997 liver
    part of                           EHDAA2:0000998  liver and biliary system
    develops from                     EHDAA2:0000740  hepatic diverticulum
    existence starts during or after  HsapDv:0000019  CS12

Complementary to `relations` rather than a substitute. This is one hop and
asserted; `relations` is Ubergraph's inference closure over ~45 ontologies.
Neither gives what the other does.
"""

NEIGHBOURS_EPILOG = r"""\
result
    { "curie": "EHDAA2:0000997",
      "ontology": "ehdaa2",
      "label": "liver",
      "outgoing": {
        "part of": [{"curie": "EHDAA2:0000998",
                     "label": "liver and biliary system"}],
        "existence starts during or after":
                   [{"curie": "HsapDv:0000019", "label": "CS12"}] },
      "incoming": {
        "part of": [{"curie": "EHDAA2:0001000", "label": "..."}] },
      "external_targets": ["AEO", "CARO", "HsapDv"] }

external_targets
  The prefixes this term points at outside its own ontology. A quick read of
  where an ontology hangs off others -- EHDAA2 liver reaches AEO and CARO for
  its upper classes and HsapDv for staging.

examples
  oq neighbours EHDAA2:0000997 -o ehdaa2

  # just the cross-ontology edges
  oq neighbours EHDAA2:0000997 -o ehdaa2 | jq -r '
    .result.outgoing | to_entries[] | .key as $p
    | .value[] | select(.curie | test("^EHDAA2:") | not)
    | "\($p)\t\(.curie)\t\(.label)"'

  # what stage does this structure start at, then read that stage in hsapdv
  oq neighbours EHDAA2:0000997 -o ehdaa2 \\
    | jq -r '.result.outgoing["existence starts during or after"][].curie'

notes
  Node labels come from OLS4's merged view of that ontology, so an imported
  term may carry the importing ontology's label rather than its home one:
  HsapDv:0000019 shows as "CS12" here and "Carnegie stage 12" in HsapDv itself.

  One hop only. There is no closure, no information content and no common
  ancestors for an ontology outside Ubergraph -- for those, cross into a
  resident ontology with `oq crosswalk` and reason there.
"""


HIERARCHY = """\
Ancestors or descendants of a term, from OLS4.

The route for ontologies Ubergraph does not hold. Both flavours are fetched by
default, because the difference between them is the thing most often got wrong:

  ancestors / descendants                  subClassOf only
  hierarchicalAncestors / ...Descendants   also the ontology's hierarchical
                                           properties, i.e. part_of and friends

For EHDAA2 liver that is 8 against 19 going up, and 0 against 26 going down.
A subsumption-only answer says the liver has no parts.

The extra terms are reported separately as reached_only_via_other_relations,
so the contribution of part_of is visible rather than merged away.
"""

HIERARCHY_EPILOG = """\
result
    { "curie": "EHDAA2:0000997",
      "direction": "down",
      "subsumption": {
        "relation": "descendants",
        "total": 0, "returned": 0, "truncated": false, "terms": [] },
      "hierarchical": {
        "relation": "hierarchicalDescendants",
        "total": 26, "returned": 26, "truncated": false,
        "reached_only_via_other_relations": [
          {"curie": "EHDAA2:0000308", "labels": ["common hepatic artery"]} ] } }

examples
  # what is this EHDAA2 structure part of, and under what classes
  oq hierarchy EHDAA2:0000997 -o ehdaa2 -d up

  # its parts
  oq hierarchy EHDAA2:0000997 -o ehdaa2 -d down \\
    | jq -r '.result.hierarchical.reached_only_via_other_relations[]
             | "\\(.curie)\\t\\(.labels[0])"'

  # subsumption alone, when that is genuinely what you want
  oq hierarchy EHDAA2:0000997 -o ehdaa2 -d up --subsumption-only

notes
  Paging: the server caps page size at 1000 and its page.totalPages is
  unusable -- it repeats totalElements -- so paging is driven from
  totalElements. At most 1000 terms are returned; `truncated` and `total` say
  when there are more. uberon:anatomical structure has 16562 hierarchical
  descendants, so a broad term will truncate.

  No information content and no common ancestors here; OLS4 has neither. For
  an ontology Ubergraph holds, `common-ancestors` is the better tool. For one
  it does not, this plus `crosswalk` is what there is.
"""
