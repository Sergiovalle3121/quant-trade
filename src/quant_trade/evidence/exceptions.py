"""Exceptions for evidence database workflows."""


class EvidenceError(Exception):
    """Base evidence error."""


class EvidenceConfigError(EvidenceError):
    """Raised when evidence configuration is invalid."""


class EvidenceDatabaseError(EvidenceError):
    """Raised when a database operation fails."""
