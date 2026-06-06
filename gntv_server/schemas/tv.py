from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, Field, IPvAnyAddress, SecretStr


class TVScreenMode(StrEnum):
    WELCOME = "welcome"
    PAIRING_PENDING = "pairing_pending"
    CASTING_INSTRUCTIONS = "casting_instructions"
    MAINTENANCE = "maintenance"
    ERROR = "error"


class CastState(StrEnum):
    STARTED = "started"
    ENDED = "ended"
    UNKNOWN = "unknown"


class TVDeviceInfo(BaseModel):
    android_id: str | None = Field(default=None, max_length=200)
    model: str | None = Field(default=None, max_length=200)
    app_version: str | None = Field(default=None, max_length=100)


class TVRegisterRequest(BaseModel):
    provisioning_token: SecretStr = Field(min_length=1)
    device_info: TVDeviceInfo = Field(default_factory=TVDeviceInfo)


class TVRegisterResult(BaseModel):
    tv_device_id: UUID
    device_token: str


class TVRoomConfig(BaseModel):
    id: UUID
    display_name: str


class TVBrandingConfig(BaseModel):
    logo_url: str | None
    background_url: str | None
    instruction_title: str
    instruction_text: str
    cast_instruction_title: str
    cast_instruction_text: str


class TVPairingConfig(BaseModel):
    pin: str = Field(pattern=r"^\d{4}$")
    qr_url: str
    expires_at: datetime


class TVScreenConfig(BaseModel):
    mode: TVScreenMode


class TVConfigResult(BaseModel):
    tv_device_id: UUID
    room: TVRoomConfig
    branding: TVBrandingConfig
    pairing: TVPairingConfig
    screen: TVScreenConfig
    poll_after_seconds: int


class TVHeartbeatRequest(BaseModel):
    app_version: str | None = Field(default=None, max_length=100)
    foreground: bool | None = None
    screen_mode: TVScreenMode | None = None
    local_ip: IPvAnyAddress | None = None


class TVHeartbeatResult(BaseModel):
    desired_screen_mode: TVScreenMode
    poll_after_seconds: int


class TVCastStateRequest(BaseModel):
    state: CastState
    session_hint: SecretStr | None = None


class TVCastStateResult(BaseModel):
    accepted: bool
