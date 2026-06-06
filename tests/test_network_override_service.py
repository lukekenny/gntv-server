import logging
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from gntv_server.models import AuditEvent, GuestSession, NetworkOverride
from gntv_server.models.enums import GuestSessionState, OverrideState
from gntv_server.services.audit import REDACTED, AuditService
from gntv_server.services.network_overrides import NetworkOverrideService
from gntv_server.services.pairing import PairingService
from tests.service_fakes import FakeAsyncSession


class FakeUniFiClient:
    def __init__(self) -> None:
        self.apply_calls: list[tuple[str, str, str]] = []
        self.clear_calls: list[tuple[str, str]] = []

    async def apply_network_override(
        self,
        user_id: str,
        network_id: str,
        site_id: str,
    ) -> dict[str, object]:
        self.apply_calls.append((user_id, network_id, site_id))
        return {"_id": user_id}

    async def clear_network_override(
        self,
        user_id: str,
        site_id: str,
    ) -> dict[str, object]:
        self.clear_calls.append((user_id, site_id))
        return {"_id": user_id}


def make_guest_session() -> GuestSession:
    now = datetime.now(UTC)
    return GuestSession(
        id=uuid4(),
        property_id=uuid4(),
        room_id=uuid4(),
        tv_device_id=uuid4(),
        guest_client_id=uuid4(),
        state=GuestSessionState.PAIRED,
        qr_token_hash=PairingService.hash_token("qr-token"),
        expires_at=now + timedelta(minutes=10),
        release_after_at=now + timedelta(hours=1),
    )


@pytest.mark.anyio
async def test_apply_override_creates_record_and_audit_event() -> None:
    session = FakeAsyncSession()
    unifi_client = FakeUniFiClient()
    service = NetworkOverrideService(
        session,  # type: ignore[arg-type]
        unifi_client=unifi_client,
    )
    guest_session = make_guest_session()
    network_id = uuid4()
    controller_id = uuid4()

    override = await service.apply_guest_override(
        guest_session=guest_session,
        guest_client_id=guest_session.guest_client_id,
        unifi_controller_id=controller_id,
        unifi_user_id="unifi-user-1",
        to_network_id=network_id,
        to_unifi_network_id="unifi-network-1",
        site_id="site-1",
    )

    audit_events = [item for item in session.added if isinstance(item, AuditEvent)]
    assert override in session.added
    assert override.state == OverrideState.APPLIED
    assert override.applied_at is not None
    assert unifi_client.apply_calls == [("unifi-user-1", "unifi-network-1", "site-1")]
    assert len(audit_events) == 1
    assert audit_events[0].event_type == "unifi.override.applied"


@pytest.mark.anyio
async def test_clear_override_disables_override_and_creates_audit_event() -> None:
    session = FakeAsyncSession()
    unifi_client = FakeUniFiClient()
    service = NetworkOverrideService(
        session,  # type: ignore[arg-type]
        unifi_client=unifi_client,
    )
    override = NetworkOverride(
        id=uuid4(),
        guest_session_id=uuid4(),
        guest_client_id=uuid4(),
        unifi_controller_id=uuid4(),
        unifi_user_id="unifi-user-1",
        to_network_id=uuid4(),
        to_unifi_network_id="unifi-network-1",
        state=OverrideState.APPLIED,
    )

    cleared = await service.clear_guest_override(
        override,
        site_id="site-1",
        property_id=uuid4(),
        reason="session_released",
    )

    audit_events = [item for item in session.added if isinstance(item, AuditEvent)]
    assert cleared is True
    assert override.state == OverrideState.RELEASED
    assert override.released_at is not None
    assert unifi_client.clear_calls == [("unifi-user-1", "site-1")]
    assert audit_events[0].event_type == "unifi.override.cleared"
    assert audit_events[0].metadata_["virtual_network_override_enabled"] is False
    assert audit_events[0].metadata_["virtual_network_override_id"] == ""


@pytest.mark.anyio
async def test_audit_service_redacts_secrets_and_does_not_log_them(
    caplog: pytest.LogCaptureFixture,
) -> None:
    session = FakeAsyncSession()
    service = AuditService(session)  # type: ignore[arg-type]
    secret = "sensitive-value"

    with caplog.at_level(logging.DEBUG):
        event = await service.create_event(
            actor_type="system",
            event_type="security.test",
            metadata={
                "unifi_api_key": secret,
                "nested": {"bearer_token": secret},
                "authorization": f"Bearer {secret}",
                "safe": "retained",
            },
        )

    assert event.metadata_["unifi_api_key"] == REDACTED
    assert event.metadata_["nested"]["bearer_token"] == REDACTED
    assert event.metadata_["authorization"] == REDACTED
    assert event.metadata_["safe"] == "retained"
    assert secret not in caplog.text
