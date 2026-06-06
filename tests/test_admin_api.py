from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from gntv_server.api.dependencies import get_unifi_client_factory
from gntv_server.core.config import Settings, get_settings
from gntv_server.db.session import get_db_session
from gntv_server.integrations.unifi import UniFiConnectivityError
from gntv_server.main import app
from gntv_server.models import (
    AuditEvent,
    Network,
    Room,
    UniFiController,
)

ADMIN_TOKEN = "test-admin-token"
AUTH_HEADERS = {"Authorization": f"Bearer {ADMIN_TOKEN}"}


class MemoryResult:
    def __init__(
        self,
        values: list[Any] | None = None,
        scalar: int | None = None,
    ) -> None:
        self.values = values or []
        self.scalar = scalar

    def scalars(self) -> "MemoryResult":
        return self

    def all(self) -> list[Any]:
        return self.values

    def scalar_one(self) -> int:
        assert self.scalar is not None
        return self.scalar


class MemoryAsyncSession:
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
                if record.updated_at is None:
                    record.updated_at = now
                else:
                    record.updated_at = now

    async def execute(self, statement: Any) -> MemoryResult:
        if "count(" in str(statement).lower():
            total = len(
                [record for record in self.records if isinstance(record, AuditEvent)]
            )
            return MemoryResult(scalar=total)

        descriptions = getattr(statement, "column_descriptions", [])
        entity = descriptions[0].get("entity") if descriptions else None
        values = [
            record
            for record in self.records
            if entity is not None and isinstance(record, entity)
        ]
        return MemoryResult(values=values)

    async def commit(self) -> None:
        self.commit_count += 1

    async def rollback(self) -> None:
        return None


class FakeUniFiClient:
    def __init__(
        self,
        *,
        networks: list[dict[str, Any]] | None = None,
        users: list[dict[str, Any]] | None = None,
        error: Exception | None = None,
    ) -> None:
        self.networks = networks or []
        self.users = users or []
        self.error = error
        self.closed = False

    async def list_networks(self) -> list[dict[str, Any]]:
        if self.error is not None:
            raise self.error
        return self.networks

    async def list_users(self) -> list[dict[str, Any]]:
        if self.error is not None:
            raise self.error
        return self.users

    async def aclose(self) -> None:
        self.closed = True


class FakeUniFiFactory:
    def __init__(self) -> None:
        self.client = FakeUniFiClient()

    def __call__(self, controller: UniFiController) -> FakeUniFiClient:
        return self.client


@pytest.fixture
def admin_api() -> tuple[TestClient, MemoryAsyncSession, FakeUniFiFactory]:
    session = MemoryAsyncSession()
    factory = FakeUniFiFactory()
    settings = Settings(
        ADMIN_TOKEN=ADMIN_TOKEN,
        UNIFI_API_KEY="not-a-real-secret",
    )

    async def override_session() -> AsyncIterator[MemoryAsyncSession]:
        yield session

    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_db_session] = override_session
    app.dependency_overrides[get_unifi_client_factory] = lambda: factory

    with TestClient(app) as client:
        yield client, session, factory

    app.dependency_overrides.clear()


def create_property(client: TestClient) -> dict[str, Any]:
    response = client.post(
        "/api/admin/properties",
        headers=AUTH_HEADERS,
        json={
            "name": "Small Creek",
            "slug": "small-creek",
            "timezone": "Australia/Sydney",
        },
    )
    assert response.status_code == 201
    return response.json()["data"]


def create_controller(client: TestClient, property_id: str) -> dict[str, Any]:
    response = client.post(
        "/api/admin/unifi/controllers",
        headers=AUTH_HEADERS,
        json={
            "property_id": property_id,
            "name": "Main UDM",
            "base_url": "https://172.16.0.1/proxy/network",
            "site": "default",
            "api_key_ref": "UNIFI_API_KEY",
            "verify_tls": False,
        },
    )
    assert response.status_code == 201
    return response.json()["data"]


def test_admin_authentication_rejects_missing_and_bad_tokens(
    admin_api: tuple[TestClient, MemoryAsyncSession, FakeUniFiFactory],
) -> None:
    client, _, _ = admin_api

    missing = client.get("/api/admin/properties")
    bad = client.get(
        "/api/admin/properties",
        headers={"Authorization": "Bearer wrong-token"},
    )
    valid = client.get("/api/admin/properties", headers=AUTH_HEADERS)

    assert missing.status_code == 401
    assert missing.headers["www-authenticate"] == "Bearer"
    assert bad.status_code == 403
    assert valid.status_code == 200


def test_create_and_list_property(
    admin_api: tuple[TestClient, MemoryAsyncSession, FakeUniFiFactory],
) -> None:
    client, _, _ = admin_api
    created = create_property(client)

    response = client.get("/api/admin/properties", headers=AUTH_HEADERS)

    assert response.status_code == 200
    assert response.json()["data"][0]["id"] == created["id"]
    assert response.json()["data"][0]["slug"] == "small-creek"


def test_room_create_list_get_update_and_soft_delete(
    admin_api: tuple[TestClient, MemoryAsyncSession, FakeUniFiFactory],
) -> None:
    client, session, _ = admin_api
    property_ = create_property(client)
    property_id = UUID(property_["id"])
    controller_id = uuid4()
    network_id = uuid4()
    session.add(
        UniFiController(
            id=controller_id,
            property_id=property_id,
            name="Main UDM",
            base_url="https://unifi.local",
            site="default",
            api_key_ref="UNIFI_API_KEY",
            verify_tls=False,
        )
    )
    session.add(
        Network(
            id=network_id,
            property_id=property_id,
            unifi_controller_id=controller_id,
            unifi_network_id="network-101",
            name="Room 101",
            raw={},
            last_synced_at=datetime.now(UTC),
        )
    )

    created = client.post(
        "/api/admin/rooms",
        headers=AUTH_HEADERS,
        json={
            "property_id": str(property_id),
            "room_code": "101",
            "display_name": "Room 101",
            "network_id": str(network_id),
            "enabled": True,
        },
    )
    room_id = created.json()["data"]["id"]
    listed = client.get("/api/admin/rooms", headers=AUTH_HEADERS)
    fetched = client.get(f"/api/admin/rooms/{room_id}", headers=AUTH_HEADERS)
    updated = client.put(
        f"/api/admin/rooms/{room_id}",
        headers=AUTH_HEADERS,
        json={"display_name": "Suite 101"},
    )
    deleted = client.delete(
        f"/api/admin/rooms/{room_id}",
        headers=AUTH_HEADERS,
    )

    assert created.status_code == 201
    assert listed.json()["data"][0]["id"] == room_id
    assert fetched.json()["data"]["room_code"] == "101"
    assert updated.json()["data"]["display_name"] == "Suite 101"
    assert deleted.json()["data"]["enabled"] is False
    assert any(
        isinstance(record, Room) and str(record.id) == room_id
        for record in session.records
    )


def test_create_and_list_unifi_controller(
    admin_api: tuple[TestClient, MemoryAsyncSession, FakeUniFiFactory],
) -> None:
    client, _, _ = admin_api
    property_ = create_property(client)
    controller = create_controller(client, property_["id"])

    response = client.get("/api/admin/unifi/controllers", headers=AUTH_HEADERS)

    assert response.status_code == 200
    assert response.json()["data"][0]["id"] == controller["id"]
    assert response.json()["data"][0]["api_key_ref"] == "UNIFI_API_KEY"


def test_unifi_controller_test_success(
    admin_api: tuple[TestClient, MemoryAsyncSession, FakeUniFiFactory],
) -> None:
    client, _, factory = admin_api
    property_ = create_property(client)
    controller = create_controller(client, property_["id"])
    factory.client = FakeUniFiClient(
        networks=[{"_id": "network-1", "name": "Room 101"}],
        users=[{"_id": "user-1"}, {"_id": "user-2"}],
    )

    response = client.post(
        f"/api/admin/unifi/controllers/{controller['id']}/test",
        headers=AUTH_HEADERS,
    )

    assert response.status_code == 200
    assert response.json()["data"] == {
        "status": "ok",
        "network_count": 1,
        "user_count": 2,
    }
    assert factory.client.closed is True


def test_unifi_controller_test_failure(
    admin_api: tuple[TestClient, MemoryAsyncSession, FakeUniFiFactory],
) -> None:
    client, _, factory = admin_api
    property_ = create_property(client)
    controller = create_controller(client, property_["id"])
    factory.client = FakeUniFiClient(
        error=UniFiConnectivityError("controller unavailable")
    )

    response = client.post(
        f"/api/admin/unifi/controllers/{controller['id']}/test",
        headers=AUTH_HEADERS,
    )

    assert response.status_code == 502
    assert response.json()["detail"] == "UniFi controller test failed"
    assert factory.client.closed is True


def test_sync_networks_upserts_unifi_records(
    admin_api: tuple[TestClient, MemoryAsyncSession, FakeUniFiFactory],
) -> None:
    client, session, factory = admin_api
    property_ = create_property(client)
    controller = create_controller(client, property_["id"])
    factory.client = FakeUniFiClient(
        networks=[
            {
                "_id": "network-101",
                "name": "Room 101",
                "vlan": 101,
                "ip_subnet": "10.101.0.1/24",
                "mdns_enabled": True,
                "network_isolation_enabled": False,
            }
        ]
    )

    first = client.post(
        f"/api/admin/unifi/controllers/{controller['id']}/sync-networks",
        headers=AUTH_HEADERS,
    )
    factory.client = FakeUniFiClient(
        networks=[{"_id": "network-101", "name": "Suite 101", "vlan": "101"}]
    )
    second = client.post(
        f"/api/admin/unifi/controllers/{controller['id']}/sync-networks",
        headers=AUTH_HEADERS,
    )

    networks = [record for record in session.records if isinstance(record, Network)]
    assert first.status_code == 200
    assert first.json()["data"] == {"created": 1, "updated": 0, "total": 1}
    assert second.json()["data"] == {"created": 0, "updated": 1, "total": 1}
    assert len(networks) == 1
    assert networks[0].name == "Suite 101"
    assert networks[0].vlan == 101


def test_audit_events_endpoint_returns_events(
    admin_api: tuple[TestClient, MemoryAsyncSession, FakeUniFiFactory],
) -> None:
    client, _, _ = admin_api
    create_property(client)

    response = client.get(
        "/api/admin/audit-events?page=1&page_size=10",
        headers=AUTH_HEADERS,
    )

    assert response.status_code == 200
    assert response.json()["data"][0]["event_type"] == "property.created"
    assert response.json()["meta"] == {
        "page": 1,
        "page_size": 10,
        "total": 1,
    }
