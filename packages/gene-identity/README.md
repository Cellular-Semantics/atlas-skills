# gene-identity

Look up which NCBI genes claim a gene or protein name exactly as a paper writes
it (`PV`, `CB`, `SOM`, `D1`). The lookup counts the claimants and says how each
was found. It never picks between them: that judgement belongs to the
`gene-id-curation` skill in `plugins/gene-identity/`.

Standard library only. Ported from evidencell's `gene_identity.py` at
[`Cellular-Semantics/evidencell@7641aab`](https://github.com/Cellular-Semantics/evidencell/tree/7641aab0ce93fbc6f434b01bf786e6095b8c7c85).
The marker-pin, KB-walking and KB hook code stayed in evidencell.

## The CLI

```
gene-id resolve --taxon NCBITaxon:10090 NAME...      Name Resolver, one species (network)
gene-id resolve --gene-table gene_ids.tsv.gz NAME... a dataset's gene table (offline)
gene-id build-table --ensembl-ids ids.txt -o gene_ids.tsv.gz [--label ID]
gene-id --version
```

`resolve` prints a JSON list, one object per name:

```json
{"name": "SOM", "method": "AMBIGUOUS", "gene": null,
 "claimants": [{"ncbi_gene_id": "NCBIGene:20604", "label": "Sst"},
               {"ncbi_gene_id": "NCBIGene:234725", "label": "Grhl3"}]}
```

| `method` | Meaning |
|---|---|
| `EXACT_SYMBOL` | the name is a gene's symbol, case-sensitive |
| `CASE_INSENSITIVE_SYMBOL` | the same ignoring case, spaces, hyphens and underscores; it beats other genes' synonyms, which stay on the match as `claimants` |
| `UNIQUE_SYNONYM` | exactly one gene lists the name. This says only that the string is unique, not that the source means that gene: `D1` → Dio1 |
| `AMBIGUOUS` | two or more claimants; none chosen |
| `NO_MATCH` | no gene of the species lists the name |

`label` is the gene's official symbol. With `--gene-table`, `symbol` is the
symbol the dataset itself uses (for example `Car8` where the official label is
now `Ca8`).

Exit codes: 0 ok, 1 the lookup could not run (Translator unreachable, or the
table is missing), 2 bad arguments.

## Gene tables

A `gene_ids.tsv.gz` records, for each Ensembl gene of a dataset, its NCBIGene
ID, official label, taxon and every name Translator Name Resolver holds for
it. A `#key<TAB>value` provenance header comes first: the Translator versions
and the fetch date. Claimants are counted over the table's genes, which is
right for a whole-transcriptome dataset but gives false "unique" results for a
targeted panel. evidencell's committed `kb/taxonomy/*/gene_ids.tsv.gz` files
load unchanged.

`build-table` reads one Ensembl ID per line, optionally followed by a tab and
the symbol the dataset uses. That symbol is kept when the gene still goes by
it; otherwise the current label wins. Version suffixes (`.5`) are stripped.
The output is deterministic, so a refresh that changes nothing produces no
diff.

## Environment

| Variable | Default |
|---|---|
| `GENE_IDENTITY_NODENORM_URL` | `https://nodenormalization-sri.renci.org` |
| `GENE_IDENTITY_NAMERES_URL` | `https://name-resolution-sri.renci.org` |

## Tests

```
pytest packages/gene-identity            # offline; HTTP is faked
pytest packages/gene-identity -m live    # hits the real Translator services
```
