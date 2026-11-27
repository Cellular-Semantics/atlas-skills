# Evals

Repo-only eval tooling, one directory per plugin. The rules, the three layers
and the target layout are in [`docs/evals.md`](../docs/evals.md). This page
lists what each plugin has and what to run.

Smoke and behaviour cases in `claude plugin eval` format ship with each plugin,
under `plugins/<plugin>/evals/`. Code-scored benchmarks and their fixtures live
here, because `claude plugin eval` cannot run code.

| Plugin | Here (repo-only) | Shipped with the plugin | Run | Cost |
|---|---|---|---|---|
| author-annotation-columns | [`author-annotation-columns/`](author-annotation-columns/README.md): 9 behaviour cases (`runner.py`), the accuracy benchmark (`benchmark.py`), the run log | 8 `smoke` cases in `plugins/author-annotation-columns/evals/smoke/` | `python3 evals/author-annotation-columns/runner.py`; `python3 evals/author-annotation-columns/benchmark.py`; `claude plugin eval author-annotation-columns --tag smoke` (flags in the plugin's `evals/README.md`) | ~$5 per behaviour suite; ~$4 per smoke run; tens of dollars for a full benchmark |
| gene-identity | [`gene-identity/`](gene-identity/README.md): the gic benchmark, 13 cases from evidencell (`gic_benchmark.py`), the run log; the record check's catch rate (`record_catch_rate.py`); the NLM-Gene tier (`--set nlm-gene --tier l4`, cases from `packages/gene-identity-eval`) | 4 `smoke` cases in `plugins/gene-identity/evals/smoke/` | `python3 evals/gene-identity/gic_benchmark.py`; `claude plugin eval gene-identity --tag smoke` (flags in the plugin's `evals/README.md`) | baseline free; ~$4 for both gic agent variants; ~$20 for the NLM-Gene l4 tier; $0.72 per smoke run |
| onto-mapping | [`onto-mapping/`](onto-mapping/README.md): JSON cases scored by `check.py` | none yet | `python evals/onto-mapping/check.py <run-file.json>` | one agent run per batch |
| paper-access | [`paper-access/`](paper-access/README.md): the manifest catch rate (`manifest_catch_rate.py`) | 3 `smoke` cases in `plugins/paper-access/evals/smoke/` | `python3 evals/paper-access/manifest_catch_rate.py` (needs the paper-access venv); `claude plugin eval paper-access --tag smoke` (flags in the plugin's `evals/README.md`) | catch rate free and offline; smoke not yet measured |
| remote-h5ad-obs | none yet | none yet | | |
| atlas-tools | none (it has no skill of its own) | none | | |

Only the free, offline parts run in `dev.sh` and CI: `pytest evals` covers the
graders, the scoring code and the case files. It never drives an agent.
