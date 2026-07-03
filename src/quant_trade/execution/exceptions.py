from __future__ import annotations


class BrokerError(RuntimeError):
    """Base broker integration error."""


class BrokerConfigurationError(BrokerError):
    """Unsafe or incomplete broker configuration."""


class BrokerSafetyError(BrokerError):
    """Order or endpoint failed closed safety validation."""


class BrokerCredentialsError(BrokerError):
    """Paper broker credentials are missing or invalid."""
