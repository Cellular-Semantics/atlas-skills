"""Evidence-returning query primitives over OLS4 and Ubergraph.

The contract: these functions return annotated evidence. They never score,
threshold, rank by relevance, or choose. Selection is the caller's judgement and
belongs in the transcript.
"""

__version__ = "0.2.0"

__all__ = ["__version__"]
