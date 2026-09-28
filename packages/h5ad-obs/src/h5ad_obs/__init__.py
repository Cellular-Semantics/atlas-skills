"""h5ad-obs: read the `obs` table out of a remote .h5ad over HTTP range requests.

Only the byte ranges backing /obs are fetched; X, layers, obsm, var and raw are
never touched. On a 476 MB atlas that is ~27 MB and ~8 s.
"""
from .reader import ReadStats, read_obs

__version__ = "0.2.0"

__all__ = ["ReadStats", "__version__", "read_obs"]
