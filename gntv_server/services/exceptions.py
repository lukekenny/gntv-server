from gntv_server.models.enums import GuestSessionState


class ServiceError(Exception):
    """Base exception for service-layer failures."""


class EntityNotFoundError(ServiceError):
    """A requested database entity does not exist."""


class InvalidStateTransitionError(ServiceError):
    def __init__(
        self,
        current: GuestSessionState,
        target: GuestSessionState,
    ) -> None:
        self.current = current
        self.target = target
        super().__init__(
            f"Guest session cannot transition from {current.value} to {target.value}"
        )


class PairingValidationError(ServiceError):
    """Pairing credentials are invalid, expired, or already consumed."""


class PairingExpiredError(PairingValidationError):
    """The pairing session or PIN has expired."""


class PairingRateLimitError(ServiceError):
    def __init__(self, retry_after_seconds: int) -> None:
        self.retry_after_seconds = retry_after_seconds
        super().__init__("Too many PIN attempts")


class ServiceConfigurationError(ServiceError):
    """Required service configuration is missing or invalid."""


class DeviceAuthenticationError(ServiceError):
    """A TV device credential is missing, invalid, or no longer active."""


class ProvisioningValidationError(ServiceError):
    """A TV provisioning token is invalid or has already been consumed."""
