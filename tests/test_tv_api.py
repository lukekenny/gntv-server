from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import parse_qs, urlparse
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from gntv_server.core.config import Settings, get_settings
from gntv_server.db.session import get_db_session
from gntv_server.main import app
from gntv_server.models import (
    AuditEvent,
    BrandingProfile,
    GuestSession,
    PairingCode,
    Room,
    TVDevice,
)
from gntv_server.models.enums import GuestSessionState, TVDeviceStatus
from gntv_server.services.security import hash_opaque_token

PROVISIONING_TOKEN = "test-provisioning-token"


class MemoryResult:
    def __init__(self, values: list[Any] | None = None) -> None:
        self.values = values or []

    def scalars(self) -> "MemoryResult":
        return self

    def all(self) -> list[Any]:
        return self.values


class TVMemorySession:
    def __init__(self) -> None:
        self.records: list[Any] = []
        self.commit_count = 0

    def add(self, instance: Any) -> None:
        if instance not in self.records:
            self.records.append(instance)

    async def get(self, model: type[Any], entity_id: UUID) -> Any | None:
        return next(
            (
                record
                for record in self.records
                if isinstance(record, model) and record.id == entity_id
            ),
            None,
        )

    async def flush(self) -> None:
        now = datetime.now(UTC)
        for record in self.records:
            if getattr(record, "id", None) is None:
                record.id = uuid4()
            if hasattr(record, "created_at") and record.created_at is None:
                record.created_at = now
            if hasattr(record, "updated_at"):
                record.updated_at = now

    async def execute(self, statement: Any) -> MemoryResult:
        descriptions = getattr(statement, "column_descriptions", [])
        entity = descriptions[0].get("entity") if descriptions else None
        query = str(statement)
        params = statement.compile().params
        values = [
            record
            for record in self.records
            if entity is not None and isinstance(record, entity)
        ]

        if entity is TVDevice:
            if self._has_parameter(params, "provisioning_token_hash"):
                token_hash = self._parameter(params, "provisioning_token_hash")
                values = [
                    device
                    for device in values
                    if device.provisioning_token_hash == token_hash
                    and device.status == TVDeviceStatus.ENROLLING
                ]
            elif self._has_parameter(params, "device_token_hash"):
                token_hash = self._parameter(params, "device_token_hash")
                values = [
                    device
                    for device in values
                    if device.device_token_hash == token_hash
                    and device.status != TVDeviceStatus.DISABLED
                ]
        elif entity is BrandingProfile:
            values.sort(key=lambda profile: profile.name)
            values = values[:1]
        elif entity is GuestSession:
            if "release_after_at >" in query:
                now = self._parameter(params, "release_after_at")
                values = [
                    guest_session
                    for guest_session in values
                    if guest_session.state == GuestSessionState.CASTING_INSTRUCTIONS
                    and guest_session.release_after_at > now
                ]
            elif "state IN" in query:
                values = [
                    guest_session
                    for guest_session in values
                    if guest_session.state
                    in {
                        GuestSessionState.IDLE,
                        GuestSessionState.PIN_DISPLAYED,
                        GuestSessionState.PAIRING_PENDING,
                    }
                ]
                values.sort(key=lambda session: session.created_at, reverse=True)
                values = values[:1]
        elif entity is PairingCode:
            now = self._parameter(params, "expires_at")
            device_id = self._parameter(params, "tv_device_id")
            values = [
                pairing_code
                for pairing_code in values
                if pairing_code.tv_device_id == device_id
                and pairing_code.consumed_at is None
                and pairing_code.expires_at > now
            ]

        return MemoryResult(values)

    async def commit(self) -> None:
        self.commit_count += 1

    async def rollback(self) -> None:
        return None

    @staticmethod
    def _parameter(params: dict[str, Any], prefix: str) -> Any:
        return next(value for key, value in params.items() if key.startswith(prefix))

    @staticmethod
    def _has_parameter(params: dict[str, Any], prefix: str) -> bool:
        return any(key.startswith(prefix) for key in params)


@pytest.fixture
def tv_api() -> tuple[TestClient, TVMemorySession, TVDevice]:
    session = TVMemorySession()
    property_id = uuid4()
    room = Room(
        id=uuid4(),
        property_id=property_id,
        room_code="101",
        display_name="Room 101",
        network_id=uuid4(),
        enabled=True,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    branding = BrandingProfile(
        id=uuid4(),
        property_id=property_id,
        name="Default",
        logo_url="https://example.test/logo.png",
        background_url="https://example.test/background.jpg",
        instruction_title="Cast to your room TV",
        instruction_text="Scan the QR code and enter the PIN.",
        cast_instruction_title="You are connected",
        cast_instruction_text="Open a Cast-enabled app.",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    device = TVDevice(
        id=uuid4(),
        room_id=room.id,
        name="Room 101 TV",
        status=TVDeviceStatus.ENROLLING,
        provisioning_token_hash=hash_opaque_token(PROVISIONING_TOKEN),
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    session.add(room)
    session.add(branding)
    session.add(device)
    settings = Settings(
        PUBLIC_BASE_URL="https://guest.example.test",
        ADMIN_TOKEN="test-admin-token",
    )

    async def override_session() -> AsyncIterator[TVMemorySession]:
        yield session

    app.dependency_overrides[get_db_session] = override_session
    app.dependency_overrides[get_settings] = lambda: settings

    with TestClient(app) as client:
        yield client, session, device

    app.dependency_overrides.clear()


def register_device(
    client: TestClient,
    *,
    provisioning_token: str = PROVISIONING_TOKEN,
) -> tuple[Any, str | None]:
    response = client.post(
        "/api/tv/register",
        json={
            "provisioning_token": provisioning_token,
            "device_info": {
                "android_id": "android-id-101",
                "model": "Google TV Streamer",
                "app_version": "0.1.0",
            },
        },
    )
    token = (
        response.json()["data"]["device_token"] if response.status_code == 200 else None
    )
    return response, token


def auth_headers(device_token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {device_token}"}


def test_register_with_valid_provisioning_token(
    tv_api: tuple[TestClient, TVMemorySession, TVDevice],
) -> None:
    client, _, device = tv_api

    response, device_token = register_device(client)

    assert response.status_code == 200
    assert response.json()["data"]["tv_device_id"] == str(device.id)
    assert device_token is not None
    assert device.status == TVDeviceStatus.PROVISIONED
    assert device.provisioning_token_hash is None
    assert device.device_token_hash == hash_opaque_token(device_token)
    assert device.device_token_hash != device_token
    assert device.android_id == "android-id-101"
    assert device.model == "Google TV Streamer"
    assert device.app_version == "0.1.0"


def test_register_rejects_invalid_provisioning_token(
    tv_api: tuple[TestClient, TVMemorySession, TVDevice],
) -> None:
    client, _, device = tv_api

    response, device_token = register_device(
        client,
        provisioning_token="invalid-provisioning-token",
    )

    assert response.status_code == 401
    assert device_token is None
    assert device.status == TVDeviceStatus.ENROLLING
    assert device.device_token_hash is None


def test_tv_endpoints_reject_missing_and_invalid_bearer_tokens(
    tv_api: tuple[TestClient, TVMemorySession, TVDevice],
) -> None:
    client, _, _ = tv_api
    register_device(client)

    for path, method in (
        ("/api/tv/config", client.get),
        ("/api/tv/heartbeat", client.post),
        ("/api/tv/cast-state", client.post),
    ):
        missing = method(path)
        invalid = method(
            path,
            headers=auth_headers("invalid-device-token"),
        )
        assert missing.status_code == 401
        assert invalid.status_code == 401


def test_config_returns_branding_pairing_and_welcome_mode(
    tv_api: tuple[TestClient, TVMemorySession, TVDevice],
) -> None:
    client, session, device = tv_api
    _, device_token = register_device(client)
    assert device_token is not None

    response = client.get(
        "/api/tv/config",
        headers=auth_headers(device_token),
    )

    data = response.json()["data"]
    assert response.status_code == 200
    assert data["tv_device_id"] == str(device.id)
    assert data["room"]["display_name"] == "Room 101"
    assert data["branding"]["logo_url"] == "https://example.test/logo.png"
    assert len(data["pairing"]["pin"]) == 4
    assert data["pairing"]["pin"].isdigit()
    assert data["pairing"]["qr_url"].startswith("https://guest.example.test/join?t=")
    assert data["pairing"]["expires_at"]
    assert data["screen"]["mode"] == "welcome"
    assert data["poll_after_seconds"] == 5
    assert any(isinstance(record, PairingCode) for record in session.records)
    assert any(isinstance(record, GuestSession) for record in session.records)


def test_config_rotates_pairing_credentials_and_stores_only_hashes(
    tv_api: tuple[TestClient, TVMemorySession, TVDevice],
) -> None:
    client, session, device = tv_api
    _, device_token = register_device(client)
    assert device_token is not None

    first = client.get("/api/tv/config", headers=auth_headers(device_token))
    first_data = first.json()["data"]["pairing"]
    first_code = next(
        record for record in session.records if isinstance(record, PairingCode)
    )
    first_expiry = first_code.expires_at

    second = client.get("/api/tv/config", headers=auth_headers(device_token))
    second_data = second.json()["data"]["pairing"]
    pairing_codes = [
        record for record in session.records if isinstance(record, PairingCode)
    ]
    guest_session = next(
        record for record in session.records if isinstance(record, GuestSession)
    )
    first_qr_token = parse_qs(urlparse(first_data["qr_url"]).query)["t"][0]
    second_qr_token = parse_qs(urlparse(second_data["qr_url"]).query)["t"][0]

    assert second.status_code == 200
    assert len(pairing_codes) == 2
    assert first_code.expires_at <= pairing_codes[1].created_at
    assert first_code.expires_at <= first_expiry
    assert all(
        code.code_hash not in {first_data["pin"], second_data["pin"]}
        for code in pairing_codes
    )
    assert guest_session.qr_token_hash == hash_opaque_token(second_qr_token)
    assert guest_session.qr_token_hash not in {first_qr_token, second_qr_token}
    assert device.device_token_hash != device_token


def test_heartbeat_updates_device_and_defaults_to_welcome(
    tv_api: tuple[TestClient, TVMemorySession, TVDevice],
) -> None:
    client, _, device = tv_api
    _, device_token = register_device(client)
    assert device_token is not None

    response = client.post(
        "/api/tv/heartbeat",
        headers=auth_headers(device_token),
        json={
            "app_version": "0.2.0",
            "foreground": True,
            "screen_mode": "welcome",
            "local_ip": "172.16.50.252",
        },
    )

    assert response.status_code == 200
    assert response.json()["data"] == {
        "desired_screen_mode": "welcome",
        "poll_after_seconds": 5,
    }
    assert device.app_version == "0.2.0"
    assert device.foreground is True
    assert device.screen_mode == "welcome"
    assert device.last_ip == "172.16.50.252"
    assert device.last_heartbeat_at is not None
    assert device.status == TVDeviceStatus.ONLINE


def test_heartbeat_returns_casting_instructions_for_active_session(
    tv_api: tuple[TestClient, TVMemorySession, TVDevice],
) -> None:
    client, session, device = tv_api
    _, device_token = register_device(client)
    assert device_token is not None
    now = datetime.now(UTC)
    session.add(
        GuestSession(
            id=uuid4(),
            property_id=uuid4(),
            room_id=device.room_id,
            tv_device_id=device.id,
            state=GuestSessionState.CASTING_INSTRUCTIONS,
            qr_token_hash=hash_opaque_token("prior-qr-token"),
            expires_at=now + timedelta(minutes=5),
            release_after_at=now + timedelta(minutes=5),
            created_at=now,
            updated_at=now,
        )
    )

    response = client.post(
        "/api/tv/heartbeat",
        headers=auth_headers(device_token),
        json={"screen_mode": "welcome"},
    )

    assert response.status_code == 200
    assert response.json()["data"]["desired_screen_mode"] == "casting_instructions"


def test_cast_state_stub_accepts_valid_and_rejects_invalid_states(
    tv_api: tuple[TestClient, TVMemorySession, TVDevice],
) -> None:
    client, session, _ = tv_api
    _, device_token = register_device(client)
    assert device_token is not None

    for state in ("started", "ended", "unknown"):
        response = client.post(
            "/api/tv/cast-state",
            headers=auth_headers(device_token),
            json={"state": state, "session_hint": "not-persisted"},
        )
        assert response.status_code == 200
        assert response.json()["data"]["accepted"] is True

    invalid = client.post(
        "/api/tv/cast-state",
        headers=auth_headers(device_token),
        json={"state": "buffering"},
    )
    cast_events = [
        record
        for record in session.records
        if isinstance(record, AuditEvent)
        and record.event_type == "tv.cast_state.reported"
    ]

    assert invalid.status_code == 422
    assert [event.metadata_["state"] for event in cast_events] == [
        "started",
        "ended",
        "unknown",
    ]
    assert all("session_hint" not in event.metadata_ for event in cast_events)
