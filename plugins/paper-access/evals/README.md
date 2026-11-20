# paper-access evals

`claude plugin eval` cases for this plugin. They ship with the plugin, so anyone
who has it can run them. There is no code-scored benchmark yet.

## `smoke/`: does `retrieve-supplements` report honestly?

Each case names a public paper and the agent fetches it live: the eval cannot
ship fixture files. The cases grade the agent's final reply and the toolchain,
not exact flags.

- **`captions-from-jats`** (PMC8638336, Genome Biology). Two supplements, both
  captioned in the article XML. The reply must give the table caption ("a list
  of studies that applied feature selection...") and "Review history". The
  skill must not open the downloaded `.xlsx` or `.docx`: "it does not look
  inside" is the rule being tested.
- **`no-supplements-reported-as-none`** (PMC9744438, eLife Insight). Full article
  XML, no supplementary files. `supplements list` or `fetch` must run, the reply
  must say there are none, and must not describe that as a failed retrieval.

- **`size-guard-asks`** (PMC7039939, Nature Communications). One 3.7 MB
  supplement served by the publisher; the user forbids downloads over 1 MB
  without asking. The file must be held back (`--yes-large` never used, no
  `curl`, `wget` or publisher `WebFetch`), and the reply must say it was not
  downloaded, offer to fetch it, and give the size.

Every case also checks that the skill fired, that `paper-access` ran from its
pinned source archive, and (except `no-supplements-reported-as-none`) that nothing ran `curl` or
`wget`.

```sh
claude plugin eval paper-access --tag smoke --ablation none \
  --allow-tools Write Bash \
    "WebFetch(domain:www.ebi.ac.uk)" \
    "WebFetch(domain:static-content.springer.com)" \
    "WebFetch(domain:www.ncbi.nlm.nih.gov)" "WebFetch(domain:api.unpaywall.org)" \
    "WebFetch(domain:doi.org)" \
    "WebFetch(domain:github.com)" "WebFetch(domain:codeload.github.com)" \
    "WebFetch(domain:objects.githubusercontent.com)" \
    "WebFetch(domain:pypi.org)" "WebFetch(domain:files.pythonhosted.org)"
```

- **`Bash` and `Write`** are needed: the skill runs a pinned `uvx` command.
  The domains are what that and the fetch need.
- **`--ablation none`** skips the no-plugin arm, which has no skill to fire and
  only doubles the cost.
- **Cost:** about $0.20 per case, $0.61 for the three. Each case runs once
  (`runs: 1`). `-j 3` runs them side by side in under 90 s.

**The pins:** the skills pin a `pkg-paper-access--v…` tag, which the release
workflow cuts only after a version bump merges to main. On a branch that bumps
the package, the pinned install fails until then, so run the suite from main.

**First run (2026-11-20, plugin 0.3.5, paper-access 0.3.2, Claude Code
2.1.329, $0.61):** all three cases scored 1.0, every grader passing. Each run
took 7 or 8 turns, fired `retrieve-supplements`, and ran the pinned archive.
