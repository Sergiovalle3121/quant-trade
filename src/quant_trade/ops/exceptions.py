class OpsError(Exception):
    """Base operations error."""


class OpsConfigError(OpsError):
    """Invalid operations config."""


class OpsValidationError(OpsError):
    """Operational validation failed."""
