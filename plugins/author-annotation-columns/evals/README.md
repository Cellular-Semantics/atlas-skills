# author-annotation-columns evals

`claude plugin eval` cases for this plugin. They ship with the plugin, so anyone
who has it can run them. The accuracy benchmark (Jaccard per tier, against the
full CL_KG gold set) is repo-only, in `evals/benchmark.py`; see
[`docs/evals.md`](https://github.com/Cellular-Semantics/atlas-skills/blob/main/docs/evals.md).

## `smoke/`: does it pick the right columns?

One case per dataset in the benchmark's light set: six from the frozen n73 tier
and two from l4 (breast, retina). Each asks a plain question and grades the
`picks.json` the skill writes:
- each curated cell-type column is picked;
- exactly as many columns as curated are picked;
- known trap columns (numeric cluster ids, constant columns) are not picked;
- the portal's `cell_type` fields are not picked;
- the skill fired.

The cases are **generated** from the gold set by `evals/smoke_cases.py` in the
repo. Do not edit them by hand; regenerate them.

```sh
claude plugin eval author-annotation-columns --tag smoke --ablation none \
  --allow-tools Write Bash \
    "WebFetch(domain:datasets.cellxgene.cziscience.com)" \
    "WebFetch(domain:github.com)" "WebFetch(domain:codeload.github.com)" \
    "WebFetch(domain:objects.githubusercontent.com)" \
    "WebFetch(domain:pypi.org)" "WebFetch(domain:files.pythonhosted.org)"
```

- **`Bash` and `Write`** are needed: the skill reads the h5ad with a pinned
  `uvx` command and writes `picks.json`. The domains are what that needs.
- **`--ablation none`** skips the no-plugin arm. Without the plugin there is no
  `picks.json`, so that arm scores near zero and only doubles the cost.
- **Cost:** about $0.40 per case for the small datasets. Each case runs once
  (`runs: 1`).

**Known gap (2026-11-18):** inside the eval's OS sandbox, the skill's toolchain
does not work as written. `uvx --from git+…` fails because macOS `git` cannot
write its `xcrun` cache under the sandbox, and `h5ad-obs` reads remote files
through aiohttp, which ignores the sandbox's HTTPS proxy. The agent then
downloads the whole h5ad with `curl` and profiles it itself. Picks are still
graded correctly, so the smoke result is meaningful for the small datasets. The
large ones (`smoke-breast-stroma-levels`, 416k cells) may time out. Outside the
eval sandbox the skill works as written. Fix tracked in
[#29](https://github.com/Cellular-Semantics/atlas-skills/issues/29).

**Known misses:**
- `smoke-constant-columns`: the picker takes `sub_cluster` (`plt_0`…`plt_4`),
  where the curators recorded no cell-type column. The published n73 run did
  the same. Expect 0.88.
- `smoke-breast-stroma-levels`: `level0` (`Stroma`/`Doublet`) is picked on some
  runs and not others. The l4 baseline left it out; the first smoke run took it.

**First full run (2026-11-19, $3.64 for 10 runs):** six of eight cases scored
1.0 and `smoke-constant-columns` scored 0.88. `smoke-constant-lineage` scored
1.0 on its picks, but on one run the agent wrote `picks.json` into a subfolder
(the prompt now rules that out), and on the re-run it could not install
`h5ad-obs` in the sandbox and gave up (#29). Until #29 is fixed, expect the odd
case to fail that way.
