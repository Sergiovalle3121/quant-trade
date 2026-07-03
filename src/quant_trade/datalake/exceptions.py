"""Data lake exceptions."""


class DataLakeError(Exception):
    """Base data lake error."""


class DatasetNotFoundError(DataLakeError):
    """Raised when a dataset is not registered."""


class ContractValidationError(DataLakeError):
    """Raised when a dataset contract fails."""
