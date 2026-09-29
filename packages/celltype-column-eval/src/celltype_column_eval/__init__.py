"""Score an agent's author-cell-type-column picks against CL_KG hand curation.

Two things live here, and nothing else:

- the **gold set** -- a frozen snapshot of the CL_KG curation sheets, the
  74-dataset CELLxGENE test set they cover, and the frozen n=73 picks that
  produced the published numbers;
- the **metrics** -- Jaccard, precision, recall, hit rate, and a random-pick
  null model, as pure functions.

Getting the picks is the agent's job, not this package's. Anything that can
produce ``{dataset_id: [column, ...]}`` can be scored here.
"""
from importlib import metadata as _metadata

from .curation import CURATION_DIR, parse_curation
from .manifest import full, subset, with_ground_truth
from .score import bootstrap_ci, hypergeom_p_hit, jaccard, score_picks, wilson

try:
    __version__ = _metadata.version("celltype-column-eval")
except _metadata.PackageNotFoundError:  # a source tree, not an install
    __version__ = "0+unknown"

__all__ = ["CURATION_DIR", "__version__", "bootstrap_ci", "full", "hypergeom_p_hit",
           "jaccard", "parse_curation", "score_picks", "subset", "wilson",
           "with_ground_truth"]
