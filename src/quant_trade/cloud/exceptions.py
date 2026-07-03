class CloudError(RuntimeError):
    """Base cloud orchestration error."""


class CloudConfigError(CloudError):
    """Invalid or unsafe cloud configuration."""


class SafetyGateError(CloudError):
    """A paper-only safety gate failed closed."""


class StorageError(CloudError):
    """Cloud storage operation failed."""


class LockError(CloudError):
    """Cloud lock operation failed."""
