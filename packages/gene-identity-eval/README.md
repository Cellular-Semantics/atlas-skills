# gene-identity-eval

Gold cases and metrics for the `gene-id-curation` skill (plugin
`gene-identity`): gene mentions from the NLM-Gene corpus, each turned into the
skill's input (`name`, `taxon`, `title`, `evidence`) with the expected record
and the lookup's own answer.

## The source

**NLM-Gene** (Islamaj R, Wei C-H, Cissel D, et al. "NLM-Gene, a richly annotated
gold standard dataset for gene entities that addresses ambiguity and
multi-species gene recognition." *J Biomed Inform* 2021;118:103779). 550 PubMed
abstracts, every gene mention annotated with NCBI Gene IDs by NLM indexers,
double-annotated to 100% agreement, across many species.

Pinned at the authors' deposit, [Zenodo record 5089049](https://zenodo.org/records/5089049)
(DOI `10.5061/dryad.dv41ns1wt`), released **CC0**. `data/nlm_gene/SOURCE.json`
records each file's checksums, the capture date, the Translator versions, and
what was excluded and why. Only the **test split** (100 abstracts) is used for
scoring; the train split is left for iterating on SKILL.md.

## From annotation to case

| NLM-Gene annotation | Expected |
|---|---|
| one NCBI Gene ID, the mention one of that gene's names | `GENE`, that gene (its current ID if NodeNorm says it was merged; the remap is recorded) |
| one NCBI Gene ID, the mention none of its names: flagged `generic` | `GENE` that gene **or** `NO_SINGLE_GENE` |
| several IDs, comma-separated: a family or class ("Wnt", "protein kinase") | `NO_SINGLE_GENE`; `kind` not scored, as the gold doesn't say family vs complex |
| several IDs, semicolon-separated: an ellipsis naming genes ("ERK1/2") | excluded |
| an ID carrying a guideline code (`-222` ...) | excluded (one in the test split) |
| no ID (`Other`, `Domain`) | excluded |
| an ID NodeNorm doesn't know, or genes of several species | excluded |

**Why `generic`.** The guidelines resolve a class with no member in the abstract
to one member gene, under a `-333` code the release dropped: "Kinases" → AKT1,
"GPCR" → Gpr34, "PKC" → one isoform, "eIF2B" → one subunit. SKILL.md asks for
`NO_SINGLE_GENE` there, and a 19-case pilot found 8 of its 10 strict failures
were exactly these. A mention is `generic` when it is neither the gene's label
nor any Name Resolver synonym, compared as the lookup compares. That test can't
tell a class from a specific name Translator doesn't list ("CCL-2", "α-SMA"),
so `generic` is a flag across strata, not a stratum, and `summarise` reports
the flagged cases apart and counts the passes that needed the allowance.

357 of the 1,441 cases are flagged.

Because `NO_SINGLE_GENE` is accepted for `generic` mentions and families, a policy that
always refuses scores well above zero (56.5% on the `l4` tier, which over-weights hard
strata; 30.3% on all 1,441). `summarise` reports it as `refuse_all_accuracy`: read
`accuracy` against it, and lead with `by_name_match.names_gene` (the strict cases).

The taxon is the gold gene's species, supplied as the caller would. The
evidence is the sentence holding the mention. A mention repeated in one
abstract with the same answer is one case.

## Strata and tiers

Each case carries `resolver_baseline`: what `gene-id resolve --taxon` alone
returned. That splits the cases by whether the skill has work to do:

| Stratum | The lookup alone... |
|---|---|
| `easy` | already gives the right gene |
| `lookup_wrong` | gives one gene, the wrong one |
| `lookup_ambiguous` | gives several claimants |
| `lookup_no_match` | finds nothing (or failed) |
| `family` | the mention names several genes |

A **tier** is a seeded, capped sample per stratum (`tiers.json`, reproducible:
a test re-derives it). `l4` over-weights the hard strata and keeps an `easy`
control, where the skill must not get in the lookup's way.

## Scoring

`metrics.score` uses the gic rules: `outcome` must match; for `GENE` the ID must
be accepted; a `kind` is checked only where the case sets one. `summarise`
reports accuracy overall and per stratum, gene-ID accuracy, family recall, the
lift over the lookup on the same cases, accuracy split by `names_gene` /
`generic`, and how many passes needed the generic allowance.

## Use

```
gene-identity-eval info              # provenance, strata, tiers
gene-identity-eval cases --tier l4   # JSON lines
```

The agent runs are in the repo: `evals/gene-identity/gic_benchmark.py --set
nlm-gene --tier l4`. Rebuilding the snapshot (network, dev-only, needs
gene-identity): `python scripts/snapshot_nlm_gene.py --work <dir>`.
