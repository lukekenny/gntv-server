from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field, IPvAnyAddress

from gntv_server.models.enums import TVDeviceStatus


class APIResponse[T](BaseModel):
    data: T
    meta: dict[str, Any] = Field(default_factory=dict)


class PropertyCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    slug: str = Field(
        min_length=1,
        max_length=100,
        pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$",
    )
    timezone: str = Field(min_length=1, max_length=100)


class PropertyRead(PropertyCreate):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    created_at: datetime
    updated_at: datetime


class UniFiControllerCreate(BaseModel):
    property_id: UUID
    name: str = Field(min_length=1, max_length=200)
    base_url: AnyHttpUrl
    site: str = Field(default="default", min_length=1, max_length=100)
    api_key_ref: str = Field(
        default="UNIFI_API_KEY",
        min_length=1,
        max_length=200,
        pattern=r"^[A-Z][A-Z0-9_]*$",
    )
    verify_tls: bool = True


class UniFiControllerRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    property_id: UUID
    name: str
    base_url: str
    site: str
    api_key_ref: str
    verify_tls: bool
    created_at: datetime
    updated_at: datetime


class UniFiTestResult(BaseModel):
    status: str
    network_count: int
    user_count: int


class NetworkSyncResult(BaseModel):
    created: int
    updated: int
    total: int


class RoomCreate(BaseModel):
    property_id: UUID
    room_code: str = Field(min_length=1, max_length=100)
    display_name: str = Field(min_length=1, max_length=200)
    network_id: UUID
    enabled: bool = True


class RoomUpdate(BaseModel):
    room_code: str | None = Field(default=None, min_length=1, max_length=100)
    display_name: str | None = Field(default=None, min_length=1, max_length=200)
    network_id: UUID | None = None
    enabled: bool | None = None


class RoomRead(RoomCreate):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    created_at: datetime
    updated_at: datetime


class TVDeviceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    room_id: UUID
    name: str
    adb_serial: str | None
    last_ip: IPvAnyAddress | None
    mac: str | None
    unifi_user_id: str | None
    unifi_network_override_id: str | None
    status: TVDeviceStatus
    app_version: str | None
    last_heartbeat_at: datetime | None
    created_at: datetime
    updated_at: datetime


class AuditEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    property_id: UUID | None
    actor_type: str
    actor_id: str | None
    event_type: str
    entity_type: str | None
    entity_id: UUID | None
    ip_address: IPvAnyAddress | None
    metadata: dict[str, Any] = Field(validation_alias="metadata_")
    created_at: datetime
