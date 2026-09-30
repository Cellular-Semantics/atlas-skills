"""Score an agent's author-annotation-column picks against hand curation.

Five field types: ``cell_type``, ``tissue``, ``development_stage``,
``other_stage`` and ``disease``.

Two things live here, and nothing else:

- the **gold set** -- a frozen snapshot of the CL_KG curation sheets (cell type
  only), the 74-dataset CELLxGENE test set they cover, the frozen n=73 picks
  that produced the published numbers, and the hand-curated per-dataset entries
  in ``data/sample_fields/`` that carry tissue, stage and disease;
- the **metrics** -- Jaccard, precision, recall, hit rate, and a random-pick
  null model, as pure functions.

Getting the picks is the agent's job, not this package's. Anything that can
produce ``{dataset_id: [column, ...]}`` can be scored here.
"""
from importlib import metadata as _metadata

from .curation import CURATION_DIR, parse_curation
from .gold import FIELD_TYPES, flatten, gold_set, notes, sample_field_gold
from .manifest import full, subset, with_ground_truth
from .score import (
    bootstrap_ci,
    hypergeom_p_hit,
    jaccard,
    score_by_field_type,
    score_picks,
    wilson,
)

try:
    __version__ = _metadata.version("obs-column-eval")
except _metadata.PackageNotFoundError:  # a source tree, not an install
    __version__ = "0+unknown"

__all__ = ["CURATION_DIR", "FIELD_TYPES", "__version__", "bootstrap_ci", "flatten",
           "full", "gold_set", "hypergeom_p_hit", "jaccard", "notes",
           "parse_curation", "sample_field_gold", "score_by_field_type",
           "score_picks", "subset", "wilson", "with_ground_truth"]
