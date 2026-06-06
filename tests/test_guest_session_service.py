from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from gntv_server.models import GuestSession
from gntv_server.models.enums import GuestSessionState
from gntv_server.services.exceptions import InvalidStateTransitionError
from gntv_server.services.guest_sessions import (
    CASTING_INSTRUCTIONS_DURATION,
    GuestSessionService,
)
from gntv_server.services.pairing import PairingService
from tests.service_fakes import FakeAsyncSession


def make_guest_session(state: GuestSessionState) -> GuestSession:
    now = datetime.now(UTC)
    return GuestSession(
        id=uuid4(),
        property_id=uuid4(),
        room_id=uuid4(),
        tv_device_id=uuid4(),
        state=state,
        qr_token_hash=PairingService.hash_token("qr-token"),
        expires_at=now + timedelta(minutes=10),
        release_after_at=now + timedelta(hours=1),
    )


def test_valid_guest_session_transitions() -> None:
    guest_session = make_guest_session(GuestSessionState.IDLE)
    transition_path = [
        GuestSessionState.PIN_DISPLAYED,
        GuestSessionState.PAIRING_PENDING,
        GuestSessionState.PAIRED,
        GuestSessionState.CASTING_INSTRUCTIONS,
        GuestSessionState.CASTING_ACTIVE,
        GuestSessionState.TIMEOUT_PENDING,
        GuestSessionState.RELEASED,
    ]

    for target in transition_path:
        GuestSessionService.transition_state(guest_session, target)

    assert guest_session.state == GuestSessionState.RELEASED
    assert guest_session.paired_at is not None
    assert guest_session.cast_started_at is not None
    assert guest_session.cast_ended_at is not None


def test_invalid_guest_session_transition() -> None:
    guest_session = make_guest_session(GuestSessionState.IDLE)

    with pytest.raises(InvalidStateTransitionError):
        GuestSessionService.transition_state(
            guest_session,
            GuestSessionState.CASTING_ACTIVE,
        )


@pytest.mark.anyio
async def test_casting_instructions_last_five_minutes() -> None:
    now = datetime.now(UTC)
    guest_session = make_guest_session(GuestSessionState.PAIRED)
    session = FakeAsyncSession()
    service = GuestSessionService(session)  # type: ignore[arg-type]

    await service.mark_casting_instructions(guest_session, now=now)

    assert guest_session.state == GuestSessionState.CASTING_INSTRUCTIONS
    assert guest_session.release_after_at == now + CASTING_INSTRUCTIONS_DURATION


class FakeOverrideReleaser:
    def __init__(self) -> None:
        self.calls = 0

    async def clear_guest_override_for_session(
        self,
        guest_session: GuestSession,
        *,
        site_id: str,
        actor_type: str = "system",
        actor_id: str | None = None,
        reason: str,
    ) -> bool:
        self.calls += 1
        return True


@pytest.mark.anyio
async def test_guest_session_release_is_idempotent() -> None:
    guest_session = make_guest_session(GuestSessionState.PAIRED)
    session = FakeAsyncSession()
    override_releaser = FakeOverrideReleaser()
    service = GuestSessionService(
        session,  # type: ignore[arg-type]
        override_service=override_releaser,
    )

    first_release = await service.release_session(
        guest_session,
        site_id="site-1",
        reason="admin_requested",
    )
    second_release = await service.release_session(
        guest_session,
        site_id="site-1",
        reason="admin_requested",
    )

    assert first_release is True
    assert second_release is False
    assert guest_session.state == GuestSessionState.RELEASED
    assert override_releaser.calls == 1


@pytest.mark.anyio
async def test_pre_pairing_session_can_be_released() -> None:
    guest_session = make_guest_session(GuestSessionState.PIN_DISPLAYED)
    session = FakeAsyncSession()
    service = GuestSessionService(session)  # type: ignore[arg-type]

    released = await service.release_session(
        guest_session,
        site_id="site-1",
        reason="pin_rotated",
    )

    assert released is True
    assert guest_session.state == GuestSessionState.RELEASED
