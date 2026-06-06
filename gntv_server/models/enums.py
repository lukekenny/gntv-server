from enum import StrEnum

from sqlalchemy import Enum


class TVDeviceStatus(StrEnum):
    ENROLLING = "enrolling"
    PROVISIONED = "provisioned"
    ONLINE = "online"
    OFFLINE = "offline"
    DISABLED = "disabled"
    ERROR = "error"


class GuestSessionState(StrEnum):
    IDLE = "idle"
    PIN_DISPLAYED = "pin_displayed"
    PAIRING_PENDING = "pairing_pending"
    PAIRED = "paired"
    CASTING_INSTRUCTIONS = "casting_instructions"
    CASTING_ACTIVE = "casting_active"
    TIMEOUT_PENDING = "timeout_pending"
    RELEASED = "released"
    EXPIRED = "expired"
    ERROR = "error"


class OverrideState(StrEnum):
    PENDING = "pending"
    APPLIED = "applied"
    RELEASE_PENDING = "release_pending"
    RELEASED = "released"
    FAILED = "failed"


class JobState(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


def migration_friendly_enum(enum_class: type[StrEnum], name: str) -> Enum:
    return Enum(
        enum_class,
        name=name,
        native_enum=False,
        create_constraint=True,
        values_callable=lambda enum_type: [item.value for item in enum_type],
        validate_strings=True,
    )
