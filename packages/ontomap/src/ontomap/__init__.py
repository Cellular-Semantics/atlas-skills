"""Map author metadata strings onto ontology terms.

The governing constraint, and the reason this package looks the way it does: a
wrong ontology ID is worse than a missing one. It is plausible, it validates, it
propagates into every downstream analysis and nothing downstream will ever
question it. So every rule here either matches exactly, proves a structural
claim, or assigns nothing at all.
"""

__version__ = "0.1.0"
