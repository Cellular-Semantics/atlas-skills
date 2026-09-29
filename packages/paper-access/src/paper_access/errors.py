"""The one exception this package raises."""

from __future__ import annotations


class PaperAccessError(Exception):
    """Something could not be done, said in terms a caller can act on.

    Deliberately one class. A caller of this package is either a CLI printing
    the message or a hook exiting non-zero, and neither branches on the type.
    """
