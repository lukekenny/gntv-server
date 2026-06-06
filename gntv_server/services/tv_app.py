from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from gntv_server.models import (
    BrandingProfile,
    GuestSession,
    Room,
    TVDevice,
)
from gntv_server.models.enums import GuestSessionState
from gntv_server.services.audit import AuditService
from gntv_server.services.exceptions import EntityNotFoundError
from gntv_server.services.guest_sessions import GuestSessionService
from gntv_server.services.pairing import PairingCredentials, PairingService
from gntv_server.services.security import hash_opaque_token

TV_POLL_AFTER_SECONDS = 5
DEFAULT_BRANDING = {
    "logo_url": None,
    "background_url": None,
    "instruction_title": "Cast to your room TV",
    "instruction_text": (
        "Connect to guest Wi-Fi, scan the QR code, enter the PIN, then choose "
        "this TV from your cast menu."
    ),
    "cast_instruction_title": "You are connected",
    "cast_instruction_text": (
        "Open a Cast-enabled app and select this TV from the Cast menu."
    ),
}


@dataclass(frozen=True, slots=True)
class TVContext:
    device: TVDevice
    room: Room
    branding: BrandingProfile | None


@dataclass(frozen=True, slots=True)
class TVConfig:
    context: TVContext
    pairing: PairingCredentials
    screen_mode: str
    poll_after_seconds: int = TV_POLL_AFTER_SECONDS


class TVAppService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_context(self, device: TVDevice) -> TVContext:
        room = await self.session.get(Room, device.room_id)
        if room is None:
            raise EntityNotFoundError(f"Room {device.room_id} was not found")

        result = await self.session.execute(
            select(BrandingProfile)
            .where(BrandingProfile.property_id == room.property_id)
            .order_by(BrandingProfile.name)
            .limit(1)
        )
        branding = next(iter(result.scalars().all()), None)
        return TVContext(device=device, room=room, branding=branding)

    async def build_config(
        self,
        device: TVDevice,
        *,
        now: datetime | None = None,
    ) -> TVConfig:
        issue_time = now or datetime.now(UTC)
        context = await self.get_context(device)
        screen_mode = await self.desired_screen_mode(device, now=issue_time)
        guest_session = await self._get_or_create_pairing_session(
            context=context,
            now=issue_time,
        )
        pairing = await PairingService(self.session).create_or_rotate_pairing_code(
            tv_device_id=device.id,
            guest_session=guest_session,
            now=issue_time,
        )
        guest_session.release_after_at = pairing.expires_at
        await self.session.flush()
        return TVConfig(
            context=context,
            pairing=pairing,
            screen_mode=screen_mode,
        )

    async def desired_screen_mode(
        self,
        device: TVDevice,
        *,
        now: datetime | None = None,
    ) -> str:
        check_time = now or datetime.now(UTC)
        result = await self.session.execute(
            select(GuestSession).where(
                GuestSession.tv_device_id == device.id,
                GuestSession.state == GuestSessionState.CASTING_INSTRUCTIONS,
                GuestSession.release_after_at > check_time,
            )
        )
        if result.scalars().all():
            return GuestSessionState.CASTING_INSTRUCTIONS.value
        return "welcome"

    async def record_cast_state(
        self,
        device: TVDevice,
        *,
        state: str,
        ip_address: str | None = None,
    ) -> None:
        context = await self.get_context(device)
        await AuditService(self.session).create_event(
            actor_type="tv_device",
            actor_id=str(device.id),
            event_type="tv.cast_state.reported",
            property_id=context.room.property_id,
            entity_type="tv_device",
            entity_id=device.id,
            ip_address=ip_address,
            metadata={"state": state},
        )

    @staticmethod
    def branding_values(branding: BrandingProfile | None) -> dict[str, Any]:
        if branding is None:
            return dict(DEFAULT_BRANDING)
        return {
            "logo_url": branding.logo_url,
            "background_url": branding.background_url,
            "instruction_title": branding.instruction_title,
            "instruction_text": branding.instruction_text,
            "cast_instruction_title": branding.cast_instruction_title,
            "cast_instruction_text": branding.cast_instruction_text,
        }

    async def _get_or_create_pairing_session(
        self,
        *,
        context: TVContext,
        now: datetime,
    ) -> GuestSession:
        reusable_states = (
            GuestSessionState.IDLE,
            GuestSessionState.PIN_DISPLAYED,
            GuestSessionState.PAIRING_PENDING,
        )
        result = await self.session.execute(
            select(GuestSession)
            .where(
                GuestSession.tv_device_id == context.device.id,
                GuestSession.state.in_(reusable_states),
            )
            .order_by(GuestSession.created_at.desc())
            .limit(1)
        )
        guest_session = next(iter(result.scalars().all()), None)
        if guest_session is not None:
            return guest_session

        placeholder_token_hash = hash_opaque_token(PairingService.generate_qr_token())
        return await GuestSessionService(self.session).create_session(
            property_id=context.room.property_id,
            room_id=context.room.id,
            tv_device_id=context.device.id,
            qr_token_hash=placeholder_token_hash,
            expires_at=now,
            release_after_at=now,
        )
