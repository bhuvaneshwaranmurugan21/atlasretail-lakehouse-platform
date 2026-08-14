"""Domain-specific failures used by the correctness kernel."""


class AtlasRetailError(Exception):
    """Base class for expected AtlasRetail failures."""


class ManifestError(AtlasRetailError):
    """A declared input manifest does not match the supplied payload."""


class ConflictError(AtlasRetailError):
    """An immutable identity was reused with different content."""


class QualityGateError(AtlasRetailError):
    """A candidate generation failed one or more correctness gates."""


class PublicationError(AtlasRetailError):
    """A generation could not be published safely."""
