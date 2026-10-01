from __future__ import annotations


class OntomapError(Exception):
    """Anything the caller did wrong, or any service that would not answer."""


class ValidationFailure(OntomapError):
    """A gate rejected a term. Never downgrade one of these to a warning."""
