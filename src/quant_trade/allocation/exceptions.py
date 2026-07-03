class AllocationError(ValueError):
    """Base allocation error."""


class AllocationConfigError(AllocationError):
    """Invalid allocation configuration."""


class AllocationEvidenceError(AllocationError):
    """Missing or invalid allocation evidence."""
