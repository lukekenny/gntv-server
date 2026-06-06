from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, SecretStr, field_validator


class GuestPairRequest(BaseModel):
    qr_token: SecretStr = Field(min_length=1)
    pin: SecretStr

    @field_validator("pin")
    @classmethod
    def validate_pin(cls, value: SecretStr) -> SecretStr:
        pin = value.get_secret_value()
        if len(pin) != 4 or not pin.isdigit():
            raise ValueError("PIN must contain exactly four digits")
        return value


class GuestPairResult(BaseModel):
    status: str
    session_id: UUID
    room_display_name: str
    message: str
    expires_at: datetime


class GuestReleaseRequest(BaseModel):
    session_token: SecretStr = Field(min_length=1)


class GuestReleaseResult(BaseModel):
    status: str
    released: bool
