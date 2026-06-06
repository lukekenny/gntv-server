from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from gntv_server.models import GuestSession
from gntv_server.models.enums import GuestSessionState
from gntv_server.services.exceptions import InvalidStateTransitionError

CASTING_INSTRUCTIONS_DURATION = timedelta(minutes=5)

ALLOWED_GUEST_SESSION_TRANSITIONS: Mapping[
    GuestSessionState,
    frozenset[GuestSessionState],
] = {
    GuestSessionState.IDLE: frozenset(
        {
            GuestSessionState.PIN_DISPLAYED,
            GuestSessionState.RELEASED,
            GuestSessionState.EXPIRED,
            GuestSessionState.ERROR,
        }
    ),
    GuestSessionState.PIN_DISPLAYED: frozenset(
        {
            GuestSessionState.PAIRING_PENDING,
            GuestSessionState.RELEASED,
            GuestSessionState.EXPIRED,
            GuestSessionState.ERROR,
        }
    ),
    GuestSessionState.PAIRING_PENDING: frozenset(
        {
            GuestSessionState.PAIRED,
            GuestSessionState.PIN_DISPLAYED,
            GuestSessionState.RELEASED,
            GuestSessionState.EXPIRED,
            GuestSessionState.ERROR,
        }
    ),
    GuestSessionState.PAIRED: frozenset(
        {
            GuestSessionState.CASTING_INSTRUCTIONS,
            GuestSessionState.RELEASED,
            GuestSessionState.EXPIRED,
            GuestSessionState.ERROR,
        }
    ),
    GuestSessionState.CASTING_INSTRUCTIONS: frozenset(
        {
            GuestSessionState.CASTING_ACTIVE,
            GuestSessionState.TIMEOUT_PENDING,
            GuestSessionState.RELEASED,
            GuestSessionState.EXPIRED,
            GuestSessionState.ERROR,
        }
    ),
    GuestSessionState.CASTING_ACTIVE: frozenset(
        {
            GuestSessionState.TIMEOUT_PENDING,
            GuestSessionState.RELEASED,
            GuestSessionState.EXPIRED,
            GuestSessionState.ERROR,
        }
    ),
    GuestSessionState.TIMEOUT_PENDING: frozenset(
        {
            GuestSessionState.RELEASED,
            GuestSessionState.EXPIRED,
            GuestSessionState.ERROR,
        }
    ),
    GuestSessionState.RELEASED: frozenset(),
    GuestSessionState.EXPIRED: frozenset(),
    GuestSessionState.ERROR: frozenset(
        {
            GuestSessionState.RELEASED,
            GuestSessionState.EXPIRED,
        }
    ),
}


class SessionOverrideReleaser(Protocol):
    async def clear_guest_override_for_session(
        self,
        guest_session: GuestSession,
        *,
        site_id: str,
        actor_type: str = "system",
        actor_id: str | None = None,
        reason: str,
    ) -> bool: ...


class GuestSessionService:
    def __init__(
        self,
        session: AsyncSession,
        *,
        override_service: SessionOverrideReleaser | None = None,
    ) -> None:
        self.session = session
        self.override_service = override_service

    async def create_session(
        self,
        *,
        property_id: UUID,
        room_id: UUID,
        tv_device_id: UUID,
        qr_token_hash: str,
        expires_at: datetime,
        release_after_at: datetime,
        pairing_code_id: UUID | None = None,
    ) -> GuestSession:
        guest_session = GuestSession(
            property_id=property_id,
            room_id=room_id,
            tv_device_id=tv_device_id,
            pairing_code_id=pairing_code_id,
            state=GuestSessionState.IDLE,
            qr_token_hash=qr_token_hash,
            expires_at=expires_at,
            release_after_at=release_after_at,
        )
        self.session.add(guest_session)
        await self.session.flush()
        return guest_session

    @staticmethod
    def transition_state(
        guest_session: GuestSession,
        target: GuestSessionState,
        *,
        now: datetime | None = None,
    ) -> GuestSession:
        if target == guest_session.state:
            return guest_session
        if target not in ALLOWED_GUEST_SESSION_TRANSITIONS[guest_session.state]:
            raise InvalidStateTransitionError(guest_session.state, target)

        transition_time = now or datetime.now(UTC)
        guest_session.state = target
        if target == GuestSessionState.PAIRED:
            guest_session.paired_at = transition_time
        elif target == GuestSessionState.CASTING_ACTIVE:
            guest_session.cast_started_at = transition_time
        elif target in {GuestSessionState.RELEASED, GuestSessionState.EXPIRED}:
            guest_session.cast_ended_at = transition_time

        return guest_session

    async def transition(
        self,
        guest_session: GuestSession,
        target: GuestSessionState,
        *,
        now: datetime | None = None,
    ) -> GuestSession:
        self.transition_state(guest_session, target, now=now)
        await self.session.flush()
        return guest_session

    async def mark_paired(
        self,
        guest_session: GuestSession,
        *,
        guest_client_id: UUID,
        now: datetime | None = None,
    ) -> GuestSession:
        guest_session.guest_client_id = guest_client_id
        self.transition_state(guest_session, GuestSessionState.PAIRED, now=now)
        await self.session.flush()
        return guest_session

    async def mark_casting_instructions(
        self,
        guest_session: GuestSession,
        *,
        now: datetime | None = None,
    ) -> GuestSession:
        transition_time = now or datetime.now(UTC)
        self.transition_state(
            guest_session,
            GuestSessionState.CASTING_INSTRUCTIONS,
            now=transition_time,
        )
        guest_session.release_after_at = transition_time + CASTING_INSTRUCTIONS_DURATION
        await self.session.flush()
        return guest_session

    async def release_session(
        self,
        guest_session: GuestSession,
        *,
        site_id: str,
        reason: str,
        actor_type: str = "system",
        actor_id: str | None = None,
        now: datetime | None = None,
    ) -> bool:
        if guest_session.state in {
            GuestSessionState.RELEASED,
            GuestSessionState.EXPIRED,
        }:
            return False

        if self.override_service is not None:
            await self.override_service.clear_guest_override_for_session(
                guest_session,
                site_id=site_id,
                actor_type=actor_type,
                actor_id=actor_id,
                reason=reason,
            )

        self.transition_state(
            guest_session,
            GuestSessionState.RELEASED,
            now=now,
        )
        await self.session.flush()
        return True

    async def expire_session(
        self,
        guest_session: GuestSession,
        *,
        site_id: str,
        reason: str = "session_expired",
        now: datetime | None = None,
    ) -> bool:
        if guest_session.state in {
            GuestSessionState.RELEASED,
            GuestSessionState.EXPIRED,
        }:
            return False

        if self.override_service is not None:
            await self.override_service.clear_guest_override_for_session(
                guest_session,
                site_id=site_id,
                reason=reason,
            )

        self.transition_state(
            guest_session,
            GuestSessionState.EXPIRED,
            now=now,
        )
        await self.session.flush()
        return True
