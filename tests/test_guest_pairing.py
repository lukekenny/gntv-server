from collections import deque
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi import Request
from fastapi.testclient import TestClient

from gntv_server.api.client_ip import get_guest_ip, resolve_client_ip
from gntv_server.api.guest import get_guest_pairing_service
from gntv_server.core.config import Settings
from gntv_server.db.session import get_db_session
from gntv_server.main import app
from gntv_server.models import (
    AuditEvent,
    GuestClient,
    GuestSession,
    Network,
    NetworkOverride,
    PairingCode,
    Room,
    TVDevice,
    UniFiController,
)
from gntv_server.models.enums import (
    GuestSessionState,
    OverrideState,
    TVDeviceStatus,
)
from gntv_server.services.exceptions import (
    PairingExpiredError,
    PairingRateLimitError,
    PairingValidationError,
)
from gntv_server.services.guest_pairing import (
    GuestPairingResult,
    GuestPairingService,
)
from gntv_server.services.pairing import PairingService

QR_TOKEN = "guest-qr-token"
PIN = "1234"
GUEST_IP = "198.51.100.25"


class QueueResult:
    def __init__(
        self,
        *,
        values: list[Any] | None = None,
        row: Any | None = None,
        scalar: int | None = None,
    ) -> None:
        self.values = values or []
        self.row = row
        self.scalar = scalar

    def scalars(self) -> "QueueResult":
        return self

    def all(self) -> list[Any]:
        return self.values

    def one_or_none(self) -> Any | None:
        return self.row

    def scalar_one(self) -> int:
        assert self.scalar is not None
        return self.scalar


class QueueSession:
    def __init__(
        self,
        *,
        objects: list[Any],
        results: list[QueueResult],
    ) -> None:
        self.objects = objects
        self.results = deque(results)
        self.added: list[Any] = []
        self.commit_count = 0
        self.rollback_count = 0

    def add(self, instance: Any) -> None:
        self.added.append(instance)
        if instance not in self.objects:
            self.objects.append(instance)

    async def get(self, model: type[Any], entity_id: UUID) -> Any | None:
        return next(
            (
                instance
                for instance in self.objects
                if isinstance(instance, model) and instance.id == entity_id
            ),
            None,
        )

    async def execute(self, statement: Any) -> QueueResult:
        assert self.results, f"Unexpected query: {statement}"
        return self.results.popleft()

    async def flush(self) -> None:
        now = datetime.now(UTC)
        for instance in self.objects:
            if getattr(instance, "id", None) is None:
                instance.id = uuid4()
            if hasattr(instance, "created_at") and instance.created_at is None:
                instance.created_at = now
            if hasattr(instance, "updated_at") and instance.updated_at is None:
                instance.updated_at = now

    async def commit(self) -> None:
        self.commit_count += 1

    async def rollback(self) -> None:
        self.rollback_count += 1


class FakeUniFiClient:
    def __init__(self) -> None:
        self.find_calls: list[str] = []
        self.apply_payloads: list[dict[str, object]] = []
        self.clear_payloads: list[dict[str, object]] = []
        self.closed = False

    async def find_user_by_ip(self, ip_address: str) -> dict[str, Any]:
        self.find_calls.append(ip_address)
        return {
            "_id": "unifi-user-1",
            "last_ip": ip_address,
            "mac": "aa:bb:cc:dd:ee:ff",
            "hostname": "guest-phone",
            "site_id": "site-id-1",
            "virtual_network_override_enabled": False,
            "virtual_network_override_id": "",
        }

    async def apply_network_override(
        self,
        user_id: str,
        network_id: str,
        site_id: str,
    ) -> dict[str, object]:
        self.apply_payloads.append(
            {
                "user_id": user_id,
                "virtual_network_override_enabled": True,
                "virtual_network_override_id": network_id,
                "site_id": site_id,
            }
        )
        return {"_id": user_id}

    async def clear_network_override(
        self,
        user_id: str,
        site_id: str,
    ) -> dict[str, object]:
        self.clear_payloads.append(
            {
                "user_id": user_id,
                "virtual_network_override_enabled": False,
                "virtual_network_override_id": "",
                "site_id": site_id,
            }
        )
        return {"_id": user_id}

    async def aclose(self) -> None:
        self.closed = True


def make_pairing_records(
    *,
    consumed: bool = False,
) -> tuple[
    GuestSession,
    PairingCode,
    Room,
    TVDevice,
    Network,
    UniFiController,
]:
    now = datetime.now(UTC)
    property_id = uuid4()
    controller = UniFiController(
        id=uuid4(),
        property_id=property_id,
        name="Main UDM",
        base_url="https://unifi.invalid",
        site="default",
        api_key_ref="UNIFI_API_KEY",
        verify_tls=False,
    )
    network = Network(
        id=uuid4(),
        property_id=property_id,
        unifi_controller_id=controller.id,
        unifi_network_id="room-network-101",
        name="Room 101",
        raw={},
        last_synced_at=now,
    )
    room = Room(
        id=uuid4(),
        property_id=property_id,
        room_code="101",
        display_name="Room 101",
        network_id=network.id,
        enabled=True,
    )
    tv_device = TVDevice(
        id=uuid4(),
        room_id=room.id,
        name="Room 101 TV",
        status=TVDeviceStatus.ONLINE,
        provisioning_token_hash=None,
        device_token_hash=PairingService.hash_token("device-token"),
    )
    pairing_code = PairingCode(
        id=uuid4(),
        tv_device_id=tv_device.id,
        code_hash=PairingService.hash_pin(PIN),
        expires_at=now + timedelta(minutes=5),
        consumed_at=now if consumed else None,
    )
    guest_session = GuestSession(
        id=uuid4(),
        property_id=property_id,
        room_id=room.id,
        tv_device_id=tv_device.id,
        pairing_code_id=pairing_code.id,
        state=GuestSessionState.PIN_DISPLAYED,
        qr_token_hash=PairingService.hash_token(QR_TOKEN),
        expires_at=now + timedelta(minutes=5),
        release_after_at=now + timedelta(minutes=5),
    )
    return (
        guest_session,
        pairing_code,
        room,
        tv_device,
        network,
        controller,
    )


@pytest.mark.anyio
async def test_valid_pairing_locates_guest_and_applies_room_override() -> None:
    records = make_pairing_records()
    guest_session, pairing_code, room, tv_device, network, controller = records
    session = QueueSession(
        objects=list(records),
        results=[
            QueueResult(row=(guest_session, pairing_code)),
            QueueResult(scalar=0),
            QueueResult(values=[]),
        ],
    )
    unifi_client = FakeUniFiClient()
    service = GuestPairingService(session)  # type: ignore[arg-type]

    result = await service.pair(
        qr_token=QR_TOKEN,
        pin=PIN,
        guest_ip=GUEST_IP,
        user_agent="guest-browser",
        client_factory=lambda _: unifi_client,
    )

    guest_client = next(item for item in session.added if isinstance(item, GuestClient))
    override = next(item for item in session.added if isinstance(item, NetworkOverride))
    assert result.room is room
    assert unifi_client.find_calls == [GUEST_IP]
    assert unifi_client.apply_payloads == [
        {
            "user_id": "unifi-user-1",
            "virtual_network_override_enabled": True,
            "virtual_network_override_id": network.unifi_network_id,
            "site_id": "site-id-1",
        }
    ]
    assert unifi_client.closed is True
    assert guest_client.last_ip == GUEST_IP
    assert guest_client.unifi_user_id == "unifi-user-1"
    assert override.state == OverrideState.APPLIED
    assert override.to_network_id == network.id
    assert pairing_code.consumed_at is not None
    assert guest_session.guest_client_id == guest_client.id
    assert guest_session.state == GuestSessionState.CASTING_INSTRUCTIONS
    assert guest_session.paired_at is not None
    assert guest_session.release_after_at <= datetime.now(UTC) + timedelta(
        minutes=5,
        seconds=2,
    )
    assert guest_session.expires_at > guest_session.release_after_at
    assert any(
        isinstance(item, AuditEvent) and item.event_type == "guest.paired"
        for item in session.added
    )
    assert controller.id == override.unifi_controller_id
    assert tv_device.id == guest_session.tv_device_id


@pytest.mark.anyio
async def test_invalid_pin_records_failed_attempt_without_calling_unifi() -> None:
    records = make_pairing_records()
    guest_session, pairing_code, *_ = records
    session = QueueSession(
        objects=list(records),
        results=[
            QueueResult(row=(guest_session, pairing_code)),
            QueueResult(scalar=0),
        ],
    )
    unifi_client = FakeUniFiClient()
    service = GuestPairingService(session)  # type: ignore[arg-type]

    with pytest.raises(PairingValidationError):
        await service.pair(
            qr_token=QR_TOKEN,
            pin="9999",
            guest_ip=GUEST_IP,
            user_agent=None,
            client_factory=lambda _: unifi_client,
        )

    assert unifi_client.find_calls == []
    assert pairing_code.consumed_at is None
    assert guest_session.state == GuestSessionState.PIN_DISPLAYED
    assert any(
        isinstance(item, AuditEvent) and item.event_type == "guest.pair.failed"
        for item in session.added
    )


@pytest.mark.anyio
async def test_consumed_pairing_code_is_rejected() -> None:
    records = make_pairing_records(consumed=True)
    guest_session, pairing_code, *_ = records
    session = QueueSession(
        objects=list(records),
        results=[QueueResult(row=(guest_session, pairing_code))],
    )
    service = GuestPairingService(session)  # type: ignore[arg-type]

    with pytest.raises(PairingValidationError):
        await service.pair(
            qr_token=QR_TOKEN,
            pin=PIN,
            guest_ip=GUEST_IP,
            user_agent=None,
            client_factory=lambda _: FakeUniFiClient(),
        )


@pytest.mark.anyio
async def test_pin_attempts_are_rate_limited_by_session_and_ip() -> None:
    records = make_pairing_records()
    guest_session, pairing_code, *_ = records
    session = QueueSession(
        objects=list(records),
        results=[
            QueueResult(row=(guest_session, pairing_code)),
            QueueResult(scalar=5),
        ],
    )
    service = GuestPairingService(
        session,  # type: ignore[arg-type]
        max_attempts=5,
    )

    with pytest.raises(PairingRateLimitError):
        await service.pair(
            qr_token=QR_TOKEN,
            pin=PIN,
            guest_ip=GUEST_IP,
            user_agent=None,
            client_factory=lambda _: FakeUniFiClient(),
        )

    assert any(
        isinstance(item, AuditEvent)
        and item.event_type == "guest.pair.rate_limited"
        and item.ip_address == GUEST_IP
        and item.entity_id == guest_session.id
        for item in session.added
    )


@pytest.mark.anyio
async def test_guest_release_clears_override_without_restoring_previous_value() -> None:
    records = make_pairing_records()
    guest_session, _, room, _, _, controller = records
    guest_session.state = GuestSessionState.CASTING_INSTRUCTIONS
    guest_session.guest_client_id = uuid4()
    override = NetworkOverride(
        id=uuid4(),
        guest_session_id=guest_session.id,
        guest_client_id=guest_session.guest_client_id,
        unifi_controller_id=controller.id,
        unifi_user_id="unifi-user-1",
        to_network_id=room.network_id,
        to_unifi_network_id="room-network-101",
        previous_override_enabled=True,
        previous_override_id="older-room-network",
        state=OverrideState.APPLIED,
    )
    session = QueueSession(
        objects=[*records, override],
        results=[
            QueueResult(values=[guest_session]),
            QueueResult(values=[override]),
        ],
    )
    unifi_client = FakeUniFiClient()
    service = GuestPairingService(session)  # type: ignore[arg-type]

    released = await service.release(
        session_token=QR_TOKEN,
        client_factory=lambda _: unifi_client,
    )

    assert released is True
    assert guest_session.state == GuestSessionState.RELEASED
    assert override.state == OverrideState.RELEASED
    assert unifi_client.clear_payloads == [
        {
            "user_id": "unifi-user-1",
            "virtual_network_override_enabled": False,
            "virtual_network_override_id": "",
            "site_id": "default",
        }
    ]
    assert unifi_client.closed is True


class RouteSession:
    def __init__(self) -> None:
        self.commit_count = 0
        self.rollback_count = 0

    async def commit(self) -> None:
        self.commit_count += 1

    async def rollback(self) -> None:
        self.rollback_count += 1


class RouteGuestService:
    def __init__(self) -> None:
        self.mode = "valid"
        self.room = SimpleNamespace(id=uuid4(), display_name="Room 101")
        self.guest_session = SimpleNamespace(
            id=uuid4(),
            expires_at=datetime.now(UTC) + timedelta(hours=4),
        )

    async def get_portal_context(self, qr_token: str) -> Any:
        if self.mode == "expired":
            raise PairingExpiredError("expired")
        if self.mode == "invalid":
            raise PairingValidationError("invalid")
        return SimpleNamespace(room=self.room)

    async def pair(self, **kwargs: Any) -> GuestPairingResult:
        if self.mode == "invalid":
            raise PairingValidationError("invalid")
        if self.mode == "rate":
            raise PairingRateLimitError(300)
        return GuestPairingResult(
            guest_session=self.guest_session,
            room=self.room,
        )

    async def release(self, **kwargs: Any) -> bool:
        return True


@pytest.fixture
def guest_routes() -> tuple[TestClient, RouteGuestService, RouteSession]:
    service = RouteGuestService()
    session = RouteSession()

    async def override_session() -> AsyncIterator[RouteSession]:
        yield session

    app.dependency_overrides[get_guest_pairing_service] = lambda: service
    app.dependency_overrides[get_db_session] = override_session
    app.dependency_overrides[get_guest_ip] = lambda: GUEST_IP
    with TestClient(app) as client:
        yield client, service, session
    app.dependency_overrides.clear()


def test_join_renders_valid_form_and_rejects_invalid_or_expired_tokens(
    guest_routes: tuple[TestClient, RouteGuestService, RouteSession],
) -> None:
    client, service, _ = guest_routes

    valid = client.get(f"/join?t={QR_TOKEN}")
    service.mode = "invalid"
    invalid = client.get("/join?t=invalid")
    service.mode = "expired"
    expired = client.get("/join?t=expired")

    assert valid.status_code == 200
    assert "Enter the PIN from the TV" in valid.text
    assert 'name="pin"' in valid.text
    assert 'name="t"' in valid.text
    assert invalid.status_code == 400
    assert "invalid or no longer available" in invalid.text
    assert expired.status_code == 410
    assert "has expired" in expired.text


def test_join_form_and_json_pair_show_success_and_validation_error(
    guest_routes: tuple[TestClient, RouteGuestService, RouteSession],
) -> None:
    client, service, session = guest_routes

    html_success = client.post(
        "/join",
        data={"t": QR_TOKEN, "pin": PIN},
    )
    json_success = client.post(
        "/api/guest/pair",
        json={"qr_token": QR_TOKEN, "pin": PIN},
    )
    service.mode = "invalid"
    html_invalid = client.post(
        "/join",
        data={"t": QR_TOKEN, "pin": "9999"},
    )
    json_invalid = client.post(
        "/api/guest/pair",
        json={"qr_token": QR_TOKEN, "pin": "9999"},
    )

    assert html_success.status_code == 200
    assert "You're connected" in html_success.text
    assert "Open a Cast-enabled app" in html_success.text
    assert json_success.status_code == 200
    assert json_success.json()["data"]["status"] == "paired"
    assert html_invalid.status_code == 400
    assert "PIN is incorrect or has expired" in html_invalid.text
    assert json_invalid.status_code == 400
    assert session.commit_count == 4


def test_guest_pair_rate_limit_and_release_endpoints(
    guest_routes: tuple[TestClient, RouteGuestService, RouteSession],
) -> None:
    client, service, session = guest_routes
    service.mode = "rate"

    limited = client.post(
        "/api/guest/pair",
        json={"qr_token": QR_TOKEN, "pin": PIN},
    )
    released = client.post(
        "/api/guest/release",
        json={"session_token": QR_TOKEN},
    )

    assert limited.status_code == 429
    assert limited.headers["retry-after"] == "300"
    assert released.status_code == 200
    assert released.json()["data"] == {
        "status": "released",
        "released": True,
    }
    assert session.commit_count == 2


def make_request(
    *,
    peer_ip: str,
    forwarded_for: str | None = None,
) -> Request:
    headers = []
    if forwarded_for is not None:
        headers.append((b"x-forwarded-for", forwarded_for.encode("ascii")))
    return Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": "GET",
            "scheme": "https",
            "path": "/join",
            "raw_path": b"/join",
            "query_string": b"",
            "headers": headers,
            "client": (peer_ip, 12345),
            "server": ("testserver", 443),
        }
    )


def test_request_ip_only_trusts_forwarded_header_from_configured_proxy() -> None:
    request = make_request(
        peer_ip="10.0.0.10",
        forwarded_for="203.0.113.44, 10.0.0.10",
    )

    direct = resolve_client_ip(
        request,
        Settings(TRUST_PROXY_HEADERS=False),
    )
    trusted = resolve_client_ip(
        request,
        Settings(
            TRUST_PROXY_HEADERS=True,
            TRUSTED_PROXY_CIDRS="10.0.0.0/8",
        ),
    )
    untrusted = resolve_client_ip(
        request,
        Settings(
            TRUST_PROXY_HEADERS=True,
            TRUSTED_PROXY_CIDRS="192.0.2.0/24",
        ),
    )

    assert direct == "10.0.0.10"
    assert trusted == "203.0.113.44"
    assert untrusted == "10.0.0.10"

    spoofed = resolve_client_ip(
        make_request(
            peer_ip="10.0.0.10",
            forwarded_for="192.0.2.99, 203.0.113.44, 10.0.0.11",
        ),
        Settings(
            TRUST_PROXY_HEADERS=True,
            TRUSTED_PROXY_CIDRS="10.0.0.0/8",
        ),
    )

    assert spoofed == "203.0.113.44"
