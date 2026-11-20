# author-annotation-columns evals

`claude plugin eval` cases for this plugin. They ship with the plugin, so anyone
who has it can run them. The accuracy benchmark (Jaccard per tier, against the
full CL_KG gold set) is repo-only, in `evals/author-annotation-columns/benchmark.py`; see
[`docs/evals.md`](https://github.com/Cellular-Semantics/atlas-skills/blob/main/docs/evals.md).

## `smoke/`: does it pick the right columns?

One case per dataset in the benchmark's light set: six from the frozen n73 tier
and two from l4 (breast, retina). Each asks a plain question and grades the
`picks.json` the skill writes:
- each curated cell-type column is picked;
- exactly as many columns as curated are picked;
- known trap columns (numeric cluster ids, constant columns) are not picked;
- the portal's `cell_type` fields are not picked;
- the skill fired;
- `h5ad-obs` ran from its pinned source archive;
- nothing ran `curl` or `wget`.

The last two check the toolchain, not the picks. When the pinned install or the
remote read failed, agents fell back to `curl` and still picked correctly, so
without them a broken toolchain scored 1.0 (#29).

The cases are **generated** from the gold set by `evals/author-annotation-columns/smoke_cases.py` in the
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

**Sandbox (fixed in 0.6.2, #29):** the skill's toolchain used to fail inside
the eval's OS sandbox: `uvx --from git+…` needed `git`, which cannot write its
`xcrun` cache there, and `h5ad-obs` ignored the sandbox's HTTPS proxy. Pins are
now source archives, which install without git, and `h5ad-obs` 0.3.2 reads
through `HTTPS_PROXY`. In two full runs after the fix, all 8 cases ran the
pinned commands with no `curl`.

**Known misses:**
- `smoke-constant-columns`: the picker takes `sub_cluster` (`plt_0`…`plt_4`),
  where the curators recorded no cell-type column. The published n73 run did
  the same. Expect 0.90.
- `smoke-breast-stroma-levels`: `level0` (`Stroma`/`Doublet`) is picked on some
  runs and not others. The l4 baseline left it out; the first smoke run took it,
  and both runs on 2026-11-19 left it out (0.83).

**First full run (2026-11-19, $4.06 for 11 runs):** seven of eight cases
scored 1.0 and `smoke-constant-columns` scored 0.88, the known miss above.
Getting there took re-runs. One run wrote `picks.json` into a subfolder, which
the prompt now rules out. Two runs could not install `h5ad-obs` in the sandbox
and gave up (#29, since fixed).

**After #29 (2026-11-19, 0.6.2, two runs, $2.09 and $2.01):** six of eight
cases scored 1.0 both times. `smoke-constant-columns` and
`smoke-breast-stroma-levels` missed as above. Every case installed `h5ad-obs`
from the archive pin, and no trace has a `curl` call. Those two runs predate the
toolchain graders, so their scores are on the old scale: 0.88 and 0.80.
