from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import CIDR, INET, JSONB, MACADDR
from sqlalchemy.orm import Mapped, mapped_column

from gntv_server.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from gntv_server.models.enums import (
    GuestSessionState,
    JobState,
    OverrideState,
    TVDeviceStatus,
    migration_friendly_enum,
)


class Property(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "properties"

    name: Mapped[str] = mapped_column(Text, nullable=False)
    slug: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    timezone: Mapped[str] = mapped_column(Text, nullable=False)


class UniFiController(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "unifi_controllers"

    property_id: Mapped[UUID] = mapped_column(
        ForeignKey("properties.id"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    base_url: Mapped[str] = mapped_column(Text, nullable=False)
    site: Mapped[str] = mapped_column(Text, nullable=False)
    api_key_ref: Mapped[str] = mapped_column(Text, nullable=False)
    verify_tls: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=text("false"),
    )


class Network(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "networks"
    __table_args__ = (
        Index(
            "uq_networks_unifi_controller_id_unifi_network_id",
            "unifi_controller_id",
            "unifi_network_id",
            unique=True,
        ),
    )

    property_id: Mapped[UUID] = mapped_column(
        ForeignKey("properties.id"),
        nullable=False,
        index=True,
    )
    unifi_controller_id: Mapped[UUID] = mapped_column(
        ForeignKey("unifi_controllers.id"),
        nullable=False,
        index=True,
    )
    unifi_network_id: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    vlan: Mapped[int | None] = mapped_column(Integer)
    ip_subnet: Mapped[str | None] = mapped_column(CIDR)
    mdns_enabled: Mapped[bool | None] = mapped_column(Boolean)
    network_isolation_enabled: Mapped[bool | None] = mapped_column(Boolean)
    raw: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
    last_synced_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )


class Room(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "rooms"
    __table_args__ = (
        Index(
            "uq_rooms_property_id_room_code", "property_id", "room_code", unique=True
        ),
    )

    property_id: Mapped[UUID] = mapped_column(
        ForeignKey("properties.id"),
        nullable=False,
        index=True,
    )
    room_code: Mapped[str] = mapped_column(Text, nullable=False)
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    network_id: Mapped[UUID] = mapped_column(
        ForeignKey("networks.id"),
        nullable=False,
        index=True,
    )
    enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=text("true"),
    )


class TVDevice(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "tv_devices"
    __table_args__ = (
        Index(
            "uq_tv_devices_device_token_hash",
            "device_token_hash",
            unique=True,
            postgresql_where=text("device_token_hash IS NOT NULL"),
        ),
    )

    room_id: Mapped[UUID] = mapped_column(
        ForeignKey("rooms.id"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    adb_serial: Mapped[str | None] = mapped_column(Text)
    last_ip: Mapped[str | None] = mapped_column(INET)
    mac: Mapped[str | None] = mapped_column(MACADDR)
    unifi_user_id: Mapped[str | None] = mapped_column(Text, index=True)
    unifi_network_override_id: Mapped[str | None] = mapped_column(Text)
    status: Mapped[TVDeviceStatus] = mapped_column(
        migration_friendly_enum(TVDeviceStatus, "tv_device_status"),
        nullable=False,
        index=True,
    )
    app_version: Mapped[str | None] = mapped_column(Text)
    provisioning_token_hash: Mapped[str | None] = mapped_column(Text)
    device_token_hash: Mapped[str | None] = mapped_column(Text)
    android_id: Mapped[str | None] = mapped_column(Text)
    model: Mapped[str | None] = mapped_column(Text)
    screen_mode: Mapped[str | None] = mapped_column(Text)
    foreground: Mapped[bool | None] = mapped_column(Boolean)
    last_heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class BrandingProfile(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "branding_profiles"

    property_id: Mapped[UUID] = mapped_column(
        ForeignKey("properties.id"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    logo_url: Mapped[str | None] = mapped_column(Text)
    background_url: Mapped[str | None] = mapped_column(Text)
    instruction_title: Mapped[str] = mapped_column(Text, nullable=False)
    instruction_text: Mapped[str] = mapped_column(Text, nullable=False)
    cast_instruction_title: Mapped[str] = mapped_column(Text, nullable=False)
    cast_instruction_text: Mapped[str] = mapped_column(Text, nullable=False)


class PairingCode(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "pairing_codes"

    tv_device_id: Mapped[UUID] = mapped_column(
        ForeignKey("tv_devices.id"),
        nullable=False,
        index=True,
    )
    code_hash: Mapped[str] = mapped_column(Text, nullable=False)
    display_code_last4: Mapped[str | None] = mapped_column(String(length=4))
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
    )
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )


class GuestClient(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "guest_clients"
    __table_args__ = (
        Index(
            "uq_guest_clients_unifi_controller_id_mac",
            "unifi_controller_id",
            "mac",
            unique=True,
            postgresql_where=text("mac IS NOT NULL"),
        ),
    )

    property_id: Mapped[UUID] = mapped_column(
        ForeignKey("properties.id"),
        nullable=False,
        index=True,
    )
    unifi_controller_id: Mapped[UUID] = mapped_column(
        ForeignKey("unifi_controllers.id"),
        nullable=False,
        index=True,
    )
    unifi_user_id: Mapped[str | None] = mapped_column(Text, index=True)
    mac: Mapped[str | None] = mapped_column(MACADDR)
    last_ip: Mapped[str] = mapped_column(INET, nullable=False, index=True)
    hostname: Mapped[str | None] = mapped_column(Text)
    user_agent: Mapped[str | None] = mapped_column(Text)
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
    )


class GuestSession(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "guest_sessions"

    property_id: Mapped[UUID] = mapped_column(
        ForeignKey("properties.id"),
        nullable=False,
        index=True,
    )
    room_id: Mapped[UUID] = mapped_column(
        ForeignKey("rooms.id"),
        nullable=False,
        index=True,
    )
    tv_device_id: Mapped[UUID] = mapped_column(
        ForeignKey("tv_devices.id"),
        nullable=False,
        index=True,
    )
    guest_client_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("guest_clients.id"),
        index=True,
    )
    pairing_code_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("pairing_codes.id"),
        index=True,
    )
    state: Mapped[GuestSessionState] = mapped_column(
        migration_friendly_enum(GuestSessionState, "guest_session_state"),
        nullable=False,
        index=True,
    )
    qr_token_hash: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    paired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cast_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cast_ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
    )
    release_after_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
    )


class NetworkOverride(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "network_overrides"

    guest_session_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("guest_sessions.id"),
        index=True,
    )
    tv_device_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("tv_devices.id"),
        index=True,
    )
    guest_client_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("guest_clients.id"),
        index=True,
    )
    unifi_controller_id: Mapped[UUID] = mapped_column(
        ForeignKey("unifi_controllers.id"),
        nullable=False,
        index=True,
    )
    unifi_user_id: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    from_network_id: Mapped[UUID | None] = mapped_column(ForeignKey("networks.id"))
    to_network_id: Mapped[UUID | None] = mapped_column(ForeignKey("networks.id"))
    to_unifi_network_id: Mapped[str] = mapped_column(Text, nullable=False)
    previous_override_enabled: Mapped[bool | None] = mapped_column(Boolean)
    previous_override_id: Mapped[str | None] = mapped_column(Text)
    state: Mapped[OverrideState] = mapped_column(
        migration_friendly_enum(OverrideState, "override_state"),
        nullable=False,
        index=True,
    )
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)


class Job(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "jobs"
    __table_args__ = (Index("ix_jobs_state_run_after", "state", "run_after"),)

    type: Mapped[str] = mapped_column(Text, nullable=False)
    state: Mapped[JobState] = mapped_column(
        migration_friendly_enum(JobState, "job_state"),
        nullable=False,
    )
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
    attempts: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default=text("0"),
    )
    run_after: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    locked_by: Mapped[str | None] = mapped_column(Text)
    last_error: Mapped[str | None] = mapped_column(Text)


class AuditEvent(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "audit_events"

    property_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("properties.id"),
        index=True,
    )
    actor_type: Mapped[str] = mapped_column(Text, nullable=False)
    actor_id: Mapped[str | None] = mapped_column(Text)
    event_type: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    entity_type: Mapped[str | None] = mapped_column(Text)
    entity_id: Mapped[UUID | None] = mapped_column(index=True)
    ip_address: Mapped[str | None] = mapped_column(INET)
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
        index=True,
    )


class UsageEvent(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "usage_events"

    property_id: Mapped[UUID] = mapped_column(
        ForeignKey("properties.id"),
        nullable=False,
        index=True,
    )
    room_id: Mapped[UUID | None] = mapped_column(ForeignKey("rooms.id"), index=True)
    tv_device_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("tv_devices.id"),
        index=True,
    )
    guest_session_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("guest_sessions.id"),
        index=True,
    )
    event_type: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
    )
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
