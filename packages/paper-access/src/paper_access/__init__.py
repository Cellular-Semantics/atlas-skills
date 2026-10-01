"""Retrieve the text of a list of papers and record honestly what arrived.

The waterfall is JATS XML, then an ASTA index-depth probe, then an open-access
PDF, then asking a person. Reading a whole paper beats retrieving from it, and
article XML is the only source carrying reference markup, guaranteed document
order, and figure and table legends. ASTA is better than a local corpus across
many papers and worse on any one paper, and omits figure legends entirely, so
it is a fallback for content rather than a preference. PDF text has no
reference markup and no guaranteed reading order across a column boundary.

The probe runs for every paper whatever route served it: no API field reports
snippet coverage, so probing is the only instrument, and the band is what tells
a later multi-paper search which papers it can reach.
"""

from __future__ import annotations

from .errors import PaperAccessError

__version__ = "0.3.0"

__all__ = ["PaperAccessError", "__version__"]
