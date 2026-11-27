# gene-identity: the gic benchmark

How often does `gene-id-curation` name the right gene, or rightly name none,
for the names a string lookup gets wrong? The 13 cases are the evidencell
`gene-id-curation` skill eval: names from real paper quotes where the lookup
(`gene-id resolve`) is ambiguous, confidently wrong, or takes a region for a gene.

| Path | Contents | Who sees it |
|---|---|---|
| `cases/gic-NN.json` | the skill's input: `name`, `taxon`, `title`, `evidence` (`source`, verbatim `text`) | the agent, minus `id` and the storage key `quote_key` |
| `answers.json` | per case: expected `outcome`, `kind`, accepted genes, how the taxon was set, the lookup's own answer (`resolver_baseline`), what the case tests | the scorer only |
| `PROVENANCE.json` | the evidencell commit and the sha256 of each YAML file the JSON was converted from | — |
| `gic_benchmark.py` | runs and scores the variants; logs each agent run | — |
| `runs/` | one committed file per run, never overwritten, and a generated index | — |

The cases and answers are copied unchanged from
[`Cellular-Semantics/evidencell@7641aab`](https://github.com/Cellular-Semantics/evidencell/tree/7641aab0ce93fbc6f434b01bf786e6095b8c7c85/research/validation/skill_evals/gene-id-curation),
YAML converted to JSON. Expected IDs came from the lookup, not from memory;
`taxon_basis` records where each taxon came from, and flags the one (gic-11)
set from background knowledge.

## Running it

```sh
python3 evals/gene-identity/gic_benchmark.py --variant baseline   # free, no agent
python3 evals/gene-identity/gic_benchmark.py                      # all three variants, ~$4
python3 evals/gene-identity/gic_benchmark.py --variant quote --case 'gic-1*' --no-log
python3 evals/gene-identity/gic_benchmark.py --dry-run            # print the prompts
```

| Variant | What runs |
|---|---|
| `baseline` | no agent: the lookup's answer scored as the record. The floor: **3/13** |
| `quote` | the case minus `title` |
| `quote-title` | the case as written |

Each agent case is a headless `claude -p` with this working tree's plugin
(`--plugin-dir plugins/gene-identity`), in an empty temporary directory,
allowed `Skill`, `Bash` and `Read`. A run whose tool calls touch this
directory or `answers.json` is **voided**, not scored. The run file records the
plugin version, the commit (and whether the plugin or package had uncommitted
changes), the exact models and the cost.

## Scoring

A case passes when `outcome` equals the expected `outcome`; for `GENE`,
`ncbi_gene_id` is one of `accept` (gic-09 accepts the mouse or the rat Chrm2);
for `NO_SINGLE_GENE` and `NOT_A_GENE_PRODUCT`, `kind` matches. `method` and
`rationale` are not scored: read them for the cases that fail, and for whether
a decision rests on the quote or on field convention.

`test_gic_benchmark.py` (offline, in `pytest evals`) keeps the case files
input-only, checks the provenance, unit-tests the scoring and the void rule,
and freezes the baseline at 3/13.

## Results

Every run is in [`runs/README.md`](runs/README.md).

**First run (2026-11-27, plugin 0.2.1 at `c3581fc`, gene-identity 0.2.0,
Claude Code 2.1.332, `claude-sonnet-5-5`):** both agent variants **13/13**,
against 3/13 for the lookup alone; $1.58 (`quote`) and $1.56 (`quote-title`).
The title made no difference: `quote` alone settled even gic-02, where the
quote says only "D1 and D2 cells", by field convention.

The skill's `method` shows how it got there. Four cases rest on field
convention rather than the quote (gic-01, -02, -06, -08: `FIELD_CONVENTION`)
and one on the lookup's single match (gic-11, `UNIQUE_SYNONYM`), so a
reviewer should read their rationale. gic-01 went by convention although its quote spells out "dopamine
D1 ... receptors", which reads as a definition.

**The set is saturated.** At 13/13 it can catch a regression but cannot rank
two versions of the skill. That is what the L4 tier (NLM-Gene, #48) is for.
