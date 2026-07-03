class TrialError(Exception):
    pass


class TrialValidationError(TrialError):
    pass


class TrialNotFoundError(TrialError):
    pass
