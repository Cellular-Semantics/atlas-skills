"""Gene or protein names as papers write them → the NCBI genes that claim them.

The contract: the lookup returns claimants and how they were found. It never
chooses between claimants; that is the curator's (or the skill's) judgement.
"""

__version__ = "0.3.1"

__all__ = ["__version__"]
