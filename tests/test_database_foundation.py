from alembic.config import Config
from alembic.script import ScriptDirectory

import gntv_server.models  # noqa: F401
from gntv_server.db.base import Base
from gntv_server.db.session import make_async_database_url
from gntv_server.models.enums import (
    GuestSessionState,
    JobState,
    OverrideState,
    TVDeviceStatus,
)


def test_models_import_and_key_tables_exist() -> None:
    expected_tables = {
        "properties",
        "unifi_controllers",
        "networks",
        "rooms",
        "tv_devices",
        "branding_profiles",
        "pairing_codes",
        "guest_clients",
        "guest_sessions",
        "network_overrides",
        "jobs",
        "audit_events",
        "usage_events",
    }

    assert expected_tables.issubset(Base.metadata.tables)


def test_tv_device_auth_columns_are_migration_ready() -> None:
    table = Base.metadata.tables["tv_devices"]

    assert table.c.provisioning_token_hash.nullable is True
    assert table.c.device_token_hash.nullable is True
    assert {
        "android_id",
        "model",
        "screen_mode",
        "foreground",
    }.issubset(table.c.keys())
    assert any(
        index.name == "uq_tv_devices_device_token_hash" and index.unique is True
        for index in table.indexes
    )


def test_alembic_has_single_head_migration() -> None:
    script = ScriptDirectory.from_config(Config("alembic.ini"))

    assert script.get_heads() == ["20260606_0002"]


def test_async_database_url_preserves_credentials() -> None:
    database_url = make_async_database_url(
        "postgresql://gntv:local-password@localhost:5432/gntv"
    )

    assert database_url == (
        "postgresql+asyncpg://gntv:local-password@localhost:5432/gntv"
    )


def test_documented_enum_values_are_present() -> None:
    assert {status.value for status in TVDeviceStatus} == {
        "enrolling",
        "provisioned",
        "online",
        "offline",
        "disabled",
        "error",
    }
    assert {state.value for state in GuestSessionState} == {
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
    }
    assert {state.value for state in OverrideState} == {
        "pending",
        "applied",
        "release_pending",
        "released",
        "failed",
    }
    assert {state.value for state in JobState} == {
        "queued",
        "running",
        "succeeded",
        "failed",
        "cancelled",
    }
