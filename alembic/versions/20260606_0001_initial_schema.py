"""Initial database schema.

Revision ID: 20260606_0001
Revises:
Create Date: 2026-06-06 00:01:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260606_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

tv_device_status = sa.Enum(
    "enrolling",
    "provisioned",
    "online",
    "offline",
    "disabled",
    "error",
    name="tv_device_status",
    native_enum=False,
    create_constraint=True,
)
guest_session_state = sa.Enum(
    "idle",
    "pin_displayed",
    "pairing_pending",
    "paired",
    "casting_instructions",
    "casting_active",
    "timeout_pending",
    "released",
    "expired",
    "error",
    name="guest_session_state",
    native_enum=False,
    create_constraint=True,
)
override_state = sa.Enum(
    "pending",
    "applied",
    "release_pending",
    "released",
    "failed",
    name="override_state",
    native_enum=False,
    create_constraint=True,
)
job_state = sa.Enum(
    "queued",
    "running",
    "succeeded",
    "failed",
    "cancelled",
    name="job_state",
    native_enum=False,
    create_constraint=True,
)


def upgrade() -> None:
    op.create_table(
        "properties",
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("slug", sa.Text(), nullable=False),
        sa.Column("timezone", sa.Text(), nullable=False),
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_properties")),
        sa.UniqueConstraint("slug", name=op.f("uq_properties_slug")),
    )

    op.create_table(
        "unifi_controllers",
        sa.Column("property_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("base_url", sa.Text(), nullable=False),
        sa.Column("site", sa.Text(), nullable=False),
        sa.Column("api_key_ref", sa.Text(), nullable=False),
        sa.Column(
            "verify_tls",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["property_id"],
            ["properties.id"],
            name=op.f("fk_unifi_controllers_property_id_properties"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_unifi_controllers")),
    )
    op.create_index(
        op.f("ix_unifi_controllers_property_id"),
        "unifi_controllers",
        ["property_id"],
    )

    op.create_table(
        "networks",
        sa.Column("property_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("unifi_controller_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("unifi_network_id", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("vlan", sa.Integer(), nullable=True),
        sa.Column("ip_subnet", postgresql.CIDR(), nullable=True),
        sa.Column("mdns_enabled", sa.Boolean(), nullable=True),
        sa.Column("network_isolation_enabled", sa.Boolean(), nullable=True),
        sa.Column(
            "raw",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["property_id"],
            ["properties.id"],
            name=op.f("fk_networks_property_id_properties"),
        ),
        sa.ForeignKeyConstraint(
            ["unifi_controller_id"],
            ["unifi_controllers.id"],
            name=op.f("fk_networks_unifi_controller_id_unifi_controllers"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_networks")),
    )
    op.create_index(op.f("ix_networks_property_id"), "networks", ["property_id"])
    op.create_index(
        op.f("ix_networks_unifi_controller_id"),
        "networks",
        ["unifi_controller_id"],
    )
    op.create_index(
        "uq_networks_unifi_controller_id_unifi_network_id",
        "networks",
        ["unifi_controller_id", "unifi_network_id"],
        unique=True,
    )

    op.create_table(
        "rooms",
        sa.Column("property_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("room_code", sa.Text(), nullable=False),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column("network_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "enabled",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["network_id"],
            ["networks.id"],
            name=op.f("fk_rooms_network_id_networks"),
        ),
        sa.ForeignKeyConstraint(
            ["property_id"],
            ["properties.id"],
            name=op.f("fk_rooms_property_id_properties"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_rooms")),
    )
    op.create_index(op.f("ix_rooms_network_id"), "rooms", ["network_id"])
    op.create_index(op.f("ix_rooms_property_id"), "rooms", ["property_id"])
    op.create_index(
        "uq_rooms_property_id_room_code",
        "rooms",
        ["property_id", "room_code"],
        unique=True,
    )

    op.create_table(
        "branding_profiles",
        sa.Column("property_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("logo_url", sa.Text(), nullable=True),
        sa.Column("background_url", sa.Text(), nullable=True),
        sa.Column("instruction_title", sa.Text(), nullable=False),
        sa.Column("instruction_text", sa.Text(), nullable=False),
        sa.Column("cast_instruction_title", sa.Text(), nullable=False),
        sa.Column("cast_instruction_text", sa.Text(), nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["property_id"],
            ["properties.id"],
            name=op.f("fk_branding_profiles_property_id_properties"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_branding_profiles")),
    )
    op.create_index(
        op.f("ix_branding_profiles_property_id"),
        "branding_profiles",
        ["property_id"],
    )

    op.create_table(
        "tv_devices",
        sa.Column("room_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("adb_serial", sa.Text(), nullable=True),
        sa.Column("last_ip", postgresql.INET(), nullable=True),
        sa.Column("mac", postgresql.MACADDR(), nullable=True),
        sa.Column("unifi_user_id", sa.Text(), nullable=True),
        sa.Column("unifi_network_override_id", sa.Text(), nullable=True),
        sa.Column("status", tv_device_status, nullable=False),
        sa.Column("app_version", sa.Text(), nullable=True),
        sa.Column("provisioning_token_hash", sa.Text(), nullable=False),
        sa.Column("last_heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["room_id"],
            ["rooms.id"],
            name=op.f("fk_tv_devices_room_id_rooms"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tv_devices")),
    )
    op.create_index(op.f("ix_tv_devices_room_id"), "tv_devices", ["room_id"])
    op.create_index(op.f("ix_tv_devices_status"), "tv_devices", ["status"])
    op.create_index(
        op.f("ix_tv_devices_unifi_user_id"),
        "tv_devices",
        ["unifi_user_id"],
    )

    op.create_table(
        "guest_clients",
        sa.Column("property_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("unifi_controller_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("unifi_user_id", sa.Text(), nullable=True),
        sa.Column("mac", postgresql.MACADDR(), nullable=True),
        sa.Column("last_ip", postgresql.INET(), nullable=False),
        sa.Column("hostname", sa.Text(), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["property_id"],
            ["properties.id"],
            name=op.f("fk_guest_clients_property_id_properties"),
        ),
        sa.ForeignKeyConstraint(
            ["unifi_controller_id"],
            ["unifi_controllers.id"],
            name=op.f("fk_guest_clients_unifi_controller_id_unifi_controllers"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_guest_clients")),
    )
    op.create_index(
        op.f("ix_guest_clients_last_ip"),
        "guest_clients",
        ["last_ip"],
    )
    op.create_index(
        op.f("ix_guest_clients_last_seen_at"),
        "guest_clients",
        ["last_seen_at"],
    )
    op.create_index(
        op.f("ix_guest_clients_property_id"),
        "guest_clients",
        ["property_id"],
    )
    op.create_index(
        op.f("ix_guest_clients_unifi_controller_id"),
        "guest_clients",
        ["unifi_controller_id"],
    )
    op.create_index(
        "uq_guest_clients_unifi_controller_id_mac",
        "guest_clients",
        ["unifi_controller_id", "mac"],
        unique=True,
        postgresql_where=sa.text("mac IS NOT NULL"),
    )
    op.create_index(
        op.f("ix_guest_clients_unifi_user_id"),
        "guest_clients",
        ["unifi_user_id"],
    )

    op.create_table(
        "pairing_codes",
        sa.Column("tv_device_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("code_hash", sa.Text(), nullable=False),
        sa.Column("display_code_last4", sa.String(length=4), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["tv_device_id"],
            ["tv_devices.id"],
            name=op.f("fk_pairing_codes_tv_device_id_tv_devices"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_pairing_codes")),
    )
    op.create_index(
        op.f("ix_pairing_codes_expires_at"),
        "pairing_codes",
        ["expires_at"],
    )
    op.create_index(
        op.f("ix_pairing_codes_tv_device_id"),
        "pairing_codes",
        ["tv_device_id"],
    )

    op.create_table(
        "guest_sessions",
        sa.Column("property_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("room_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tv_device_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("guest_client_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("pairing_code_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("state", guest_session_state, nullable=False),
        sa.Column("qr_token_hash", sa.Text(), nullable=False),
        sa.Column("paired_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cast_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cast_ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("release_after_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["guest_client_id"],
            ["guest_clients.id"],
            name=op.f("fk_guest_sessions_guest_client_id_guest_clients"),
        ),
        sa.ForeignKeyConstraint(
            ["pairing_code_id"],
            ["pairing_codes.id"],
            name=op.f("fk_guest_sessions_pairing_code_id_pairing_codes"),
        ),
        sa.ForeignKeyConstraint(
            ["property_id"],
            ["properties.id"],
            name=op.f("fk_guest_sessions_property_id_properties"),
        ),
        sa.ForeignKeyConstraint(
            ["room_id"],
            ["rooms.id"],
            name=op.f("fk_guest_sessions_room_id_rooms"),
        ),
        sa.ForeignKeyConstraint(
            ["tv_device_id"],
            ["tv_devices.id"],
            name=op.f("fk_guest_sessions_tv_device_id_tv_devices"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_guest_sessions")),
    )
    op.create_index(
        op.f("ix_guest_sessions_expires_at"),
        "guest_sessions",
        ["expires_at"],
    )
    op.create_index(
        op.f("ix_guest_sessions_guest_client_id"),
        "guest_sessions",
        ["guest_client_id"],
    )
    op.create_index(
        op.f("ix_guest_sessions_pairing_code_id"),
        "guest_sessions",
        ["pairing_code_id"],
    )
    op.create_index(
        op.f("ix_guest_sessions_property_id"),
        "guest_sessions",
        ["property_id"],
    )
    op.create_index(
        op.f("ix_guest_sessions_qr_token_hash"),
        "guest_sessions",
        ["qr_token_hash"],
    )
    op.create_index(
        op.f("ix_guest_sessions_release_after_at"),
        "guest_sessions",
        ["release_after_at"],
    )
    op.create_index(op.f("ix_guest_sessions_room_id"), "guest_sessions", ["room_id"])
    op.create_index(op.f("ix_guest_sessions_state"), "guest_sessions", ["state"])
    op.create_index(
        op.f("ix_guest_sessions_tv_device_id"),
        "guest_sessions",
        ["tv_device_id"],
    )

    op.create_table(
        "jobs",
        sa.Column("type", sa.Text(), nullable=False),
        sa.Column("state", job_state, nullable=False),
        sa.Column(
            "payload",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "attempts", sa.Integer(), server_default=sa.text("0"), nullable=False
        ),
        sa.Column("run_after", sa.DateTime(timezone=True), nullable=False),
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("locked_by", sa.Text(), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_jobs")),
    )
    op.create_index("ix_jobs_state_run_after", "jobs", ["state", "run_after"])

    op.create_table(
        "network_overrides",
        sa.Column("guest_session_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("tv_device_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("guest_client_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("unifi_controller_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("unifi_user_id", sa.Text(), nullable=False),
        sa.Column("from_network_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("to_network_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("to_unifi_network_id", sa.Text(), nullable=False),
        sa.Column("previous_override_enabled", sa.Boolean(), nullable=True),
        sa.Column("previous_override_id", sa.Text(), nullable=True),
        sa.Column("state", override_state, nullable=False),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("released_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["from_network_id"],
            ["networks.id"],
            name=op.f("fk_network_overrides_from_network_id_networks"),
        ),
        sa.ForeignKeyConstraint(
            ["guest_client_id"],
            ["guest_clients.id"],
            name=op.f("fk_network_overrides_guest_client_id_guest_clients"),
        ),
        sa.ForeignKeyConstraint(
            ["guest_session_id"],
            ["guest_sessions.id"],
            name=op.f("fk_network_overrides_guest_session_id_guest_sessions"),
        ),
        sa.ForeignKeyConstraint(
            ["to_network_id"],
            ["networks.id"],
            name=op.f("fk_network_overrides_to_network_id_networks"),
        ),
        sa.ForeignKeyConstraint(
            ["tv_device_id"],
            ["tv_devices.id"],
            name=op.f("fk_network_overrides_tv_device_id_tv_devices"),
        ),
        sa.ForeignKeyConstraint(
            ["unifi_controller_id"],
            ["unifi_controllers.id"],
            name=op.f("fk_network_overrides_unifi_controller_id_unifi_controllers"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_network_overrides")),
    )
    op.create_index(
        op.f("ix_network_overrides_guest_client_id"),
        "network_overrides",
        ["guest_client_id"],
    )
    op.create_index(
        op.f("ix_network_overrides_guest_session_id"),
        "network_overrides",
        ["guest_session_id"],
    )
    op.create_index(
        op.f("ix_network_overrides_state"),
        "network_overrides",
        ["state"],
    )
    op.create_index(
        op.f("ix_network_overrides_tv_device_id"),
        "network_overrides",
        ["tv_device_id"],
    )
    op.create_index(
        op.f("ix_network_overrides_unifi_controller_id"),
        "network_overrides",
        ["unifi_controller_id"],
    )
    op.create_index(
        op.f("ix_network_overrides_unifi_user_id"),
        "network_overrides",
        ["unifi_user_id"],
    )

    op.create_table(
        "audit_events",
        sa.Column("property_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("actor_type", sa.Text(), nullable=False),
        sa.Column("actor_id", sa.Text(), nullable=True),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("entity_type", sa.Text(), nullable=True),
        sa.Column("entity_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("ip_address", postgresql.INET(), nullable=True),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["property_id"],
            ["properties.id"],
            name=op.f("fk_audit_events_property_id_properties"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_events")),
    )
    op.create_index(
        op.f("ix_audit_events_created_at"),
        "audit_events",
        ["created_at"],
    )
    op.create_index(
        op.f("ix_audit_events_entity_id"),
        "audit_events",
        ["entity_id"],
    )
    op.create_index(
        op.f("ix_audit_events_event_type"),
        "audit_events",
        ["event_type"],
    )
    op.create_index(
        op.f("ix_audit_events_property_id"),
        "audit_events",
        ["property_id"],
    )

    op.create_table(
        "usage_events",
        sa.Column("property_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("room_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("tv_device_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("guest_session_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["guest_session_id"],
            ["guest_sessions.id"],
            name=op.f("fk_usage_events_guest_session_id_guest_sessions"),
        ),
        sa.ForeignKeyConstraint(
            ["property_id"],
            ["properties.id"],
            name=op.f("fk_usage_events_property_id_properties"),
        ),
        sa.ForeignKeyConstraint(
            ["room_id"],
            ["rooms.id"],
            name=op.f("fk_usage_events_room_id_rooms"),
        ),
        sa.ForeignKeyConstraint(
            ["tv_device_id"],
            ["tv_devices.id"],
            name=op.f("fk_usage_events_tv_device_id_tv_devices"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_usage_events")),
    )
    op.create_index(
        op.f("ix_usage_events_event_type"),
        "usage_events",
        ["event_type"],
    )
    op.create_index(
        op.f("ix_usage_events_guest_session_id"),
        "usage_events",
        ["guest_session_id"],
    )
    op.create_index(
        op.f("ix_usage_events_occurred_at"),
        "usage_events",
        ["occurred_at"],
    )
    op.create_index(
        op.f("ix_usage_events_property_id"),
        "usage_events",
        ["property_id"],
    )
    op.create_index(op.f("ix_usage_events_room_id"), "usage_events", ["room_id"])
    op.create_index(
        op.f("ix_usage_events_tv_device_id"),
        "usage_events",
        ["tv_device_id"],
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_usage_events_tv_device_id"), table_name="usage_events")
    op.drop_index(op.f("ix_usage_events_room_id"), table_name="usage_events")
    op.drop_index(op.f("ix_usage_events_property_id"), table_name="usage_events")
    op.drop_index(op.f("ix_usage_events_occurred_at"), table_name="usage_events")
    op.drop_index(op.f("ix_usage_events_guest_session_id"), table_name="usage_events")
    op.drop_index(op.f("ix_usage_events_event_type"), table_name="usage_events")
    op.drop_table("usage_events")
    op.drop_index(op.f("ix_audit_events_property_id"), table_name="audit_events")
    op.drop_index(op.f("ix_audit_events_event_type"), table_name="audit_events")
    op.drop_index(op.f("ix_audit_events_entity_id"), table_name="audit_events")
    op.drop_index(op.f("ix_audit_events_created_at"), table_name="audit_events")
    op.drop_table("audit_events")
    op.drop_index(
        op.f("ix_network_overrides_unifi_user_id"),
        table_name="network_overrides",
    )
    op.drop_index(
        op.f("ix_network_overrides_unifi_controller_id"),
        table_name="network_overrides",
    )
    op.drop_index(
        op.f("ix_network_overrides_tv_device_id"), table_name="network_overrides"
    )
    op.drop_index(op.f("ix_network_overrides_state"), table_name="network_overrides")
    op.drop_index(
        op.f("ix_network_overrides_guest_session_id"),
        table_name="network_overrides",
    )
    op.drop_index(
        op.f("ix_network_overrides_guest_client_id"),
        table_name="network_overrides",
    )
    op.drop_table("network_overrides")
    op.drop_index("ix_jobs_state_run_after", table_name="jobs")
    op.drop_table("jobs")
    op.drop_index(op.f("ix_guest_sessions_tv_device_id"), table_name="guest_sessions")
    op.drop_index(op.f("ix_guest_sessions_state"), table_name="guest_sessions")
    op.drop_index(op.f("ix_guest_sessions_room_id"), table_name="guest_sessions")
    op.drop_index(
        op.f("ix_guest_sessions_release_after_at"),
        table_name="guest_sessions",
    )
    op.drop_index(
        op.f("ix_guest_sessions_qr_token_hash"),
        table_name="guest_sessions",
    )
    op.drop_index(op.f("ix_guest_sessions_property_id"), table_name="guest_sessions")
    op.drop_index(
        op.f("ix_guest_sessions_pairing_code_id"),
        table_name="guest_sessions",
    )
    op.drop_index(
        op.f("ix_guest_sessions_guest_client_id"),
        table_name="guest_sessions",
    )
    op.drop_index(op.f("ix_guest_sessions_expires_at"), table_name="guest_sessions")
    op.drop_table("guest_sessions")
    op.drop_index(op.f("ix_pairing_codes_tv_device_id"), table_name="pairing_codes")
    op.drop_index(op.f("ix_pairing_codes_expires_at"), table_name="pairing_codes")
    op.drop_table("pairing_codes")
    op.drop_index(op.f("ix_guest_clients_unifi_user_id"), table_name="guest_clients")
    op.drop_index(
        "uq_guest_clients_unifi_controller_id_mac",
        table_name="guest_clients",
    )
    op.drop_index(
        op.f("ix_guest_clients_unifi_controller_id"),
        table_name="guest_clients",
    )
    op.drop_index(op.f("ix_guest_clients_property_id"), table_name="guest_clients")
    op.drop_index(op.f("ix_guest_clients_last_seen_at"), table_name="guest_clients")
    op.drop_index(op.f("ix_guest_clients_last_ip"), table_name="guest_clients")
    op.drop_table("guest_clients")
    op.drop_index(op.f("ix_tv_devices_unifi_user_id"), table_name="tv_devices")
    op.drop_index(op.f("ix_tv_devices_status"), table_name="tv_devices")
    op.drop_index(op.f("ix_tv_devices_room_id"), table_name="tv_devices")
    op.drop_table("tv_devices")
    op.drop_index(
        op.f("ix_branding_profiles_property_id"),
        table_name="branding_profiles",
    )
    op.drop_table("branding_profiles")
    op.drop_index("uq_rooms_property_id_room_code", table_name="rooms")
    op.drop_index(op.f("ix_rooms_property_id"), table_name="rooms")
    op.drop_index(op.f("ix_rooms_network_id"), table_name="rooms")
    op.drop_table("rooms")
    op.drop_index(
        "uq_networks_unifi_controller_id_unifi_network_id",
        table_name="networks",
    )
    op.drop_index(op.f("ix_networks_unifi_controller_id"), table_name="networks")
    op.drop_index(op.f("ix_networks_property_id"), table_name="networks")
    op.drop_table("networks")
    op.drop_index(
        op.f("ix_unifi_controllers_property_id"),
        table_name="unifi_controllers",
    )
    op.drop_table("unifi_controllers")
    op.drop_table("properties")
