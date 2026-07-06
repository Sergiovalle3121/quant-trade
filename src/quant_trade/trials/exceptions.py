class TrialError(Exception):
    pass


class TrialValidationError(TrialError):
    pass


class TrialNotFoundError(TrialError):
    pass


class TrialDataMissingError(TrialError):
    """Raised when a trial has no real daily records; data is never fabricated."""
