# gene-identity evals

`claude plugin eval` cases for this plugin. They ship with the plugin, so anyone
who has it can run them. The code-scored benchmark over 13 cases from evidencell
is repo-only: `evals/gene-identity/` in the atlas-skills repo.

## `smoke/`: does `gene-id-curation` avoid the traps it exists for?

Each case gives one name, a taxon and (all but one) an evidence sentence, and asks for the
record in `result.gene-records.json`. Graders read that file, so they check the
record the skill would hand on, not the wording of the reply.

- **`d1-quote-overrides-lookup`** (PMID:37546856, evidencell gic-01). The lookup
  says `D1` is Dio1, its only claimant; the quote says "dopamine D1 or D2
  receptors". The gene must be Drd1 (NCBIGene:13488), not Dio1, and the skill
  must look up the dopamine receptor rather than write its ID from memory.
- **`sp-region-not-a-gene`** (PMID:42268975, gic-04). "the SO and SP layers of
  CA1-CA3": `SP` is stratum pyramidale. The lookup offers four genes, Tac1
  (substance P) among them. The record must be `NOT_A_GENE_PRODUCT` /
  `NON_GENE_TERM` with no gene ID.
- **`camkii-family`** (constructed sentence). CaMKII names four genes and the
  sentence names no subunit; the lookup offers three of them. The record must
  be `NO_SINGLE_GENE` / `GENE_FAMILY`, not one member.
- **`neun-antibody`** (constructed sentence). NeuN is an antibody to Rbfox3.
  The record must give Rbfox3 (NCBIGene:52897) as `symbol`, with `antibody`
  set to `NeuN`.
- **`crf-no-evidence`** (constructed). `CRF` is claimed by Crh and C1ql1, and
  the input has no evidence and no title. The record must be `UNRESOLVED` /
  `AMBIGUOUS`: with no field there is no convention to settle it by.

Every case also checks that the skill fired, that `gene-id` ran from its pinned
source archive, that the record file was written and run through
`gene-id validate`. The two GENE cases also check that `gene-id resolve` ran:
Step 1 settles regions and families without a lookup, so the other two do not.

```sh
claude plugin eval plugins/gene-identity --tag smoke --ablation none -j 4 \
  --allow-tools Write Bash \
    "WebFetch(domain:name-resolution-sri.renci.org)" \
    "WebFetch(domain:nodenormalization-sri.renci.org)" \
    "WebFetch(domain:github.com)" "WebFetch(domain:codeload.github.com)" \
    "WebFetch(domain:objects.githubusercontent.com)" \
    "WebFetch(domain:pypi.org)" "WebFetch(domain:files.pythonhosted.org)"
```

- **`Bash` and `Write`** are needed: the skill runs a pinned `uvx` command and
  writes the record. The domains are what the install and the lookup need.
- **`--ablation none`** skips the no-plugin arm, which has no skill to fire.
- **Cost:** about $0.18 per case, $0.72 for the four, ~35 s with `-j 4`.

**First run (2026-11-27, plugin 0.2.0, gene-identity 0.2.0, Claude Code
2.1.332, $0.72):** all four cases scored 1.00. An earlier run the same day
scored 0.88–0.89 on three cases, every miss a grader error: `ran-resolve` was
required on the region and family cases, which correctly never reach the
lookup, and `not-dio1` matched Dio1's ID where the rationale named it.
