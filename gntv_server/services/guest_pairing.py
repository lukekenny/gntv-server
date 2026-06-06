from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from gntv_server.integrations.unifi import UniFiMalformedResponseError
from gntv_server.models import (
    AuditEvent,
    GuestClient,
    GuestSession,
    Network,
    Room,
    TVDevice,
    UniFiController,
)
from gntv_server.models.enums import TVDeviceStatus
from gntv_server.services.audit import AuditService
from gntv_server.services.exceptions import (
    EntityNotFoundError,
    PairingRateLimitError,
    PairingValidationError,
)
from gntv_server.services.guest_sessions import GuestSessionService
from gntv_server.services.network_overrides import NetworkOverrideService
from gntv_server.services.pairing import PairingService, ValidatedPairing

PAIR_FAILURE_EVENT = "guest.pair.failed"


class GuestUniFiClient(Protocol):
    async def find_user_by_ip(self, ip_address: str) -> dict[str, Any]: ...

    async def apply_network_override(
        self,
        user_id: str,
        network_id: str,
        site_id: str,
    ) -> dict[str, object] | None: ...

    async def clear_network_override(
        self,
        user_id: str,
        site_id: str,
    ) -> dict[str, object] | None: ...

    async def aclose(self) -> None: ...


type GuestUniFiClientFactory = Callable[[UniFiController], GuestUniFiClient]


@dataclass(frozen=True, slots=True)
class GuestPairingContext:
    pairing: ValidatedPairing
    room: Room
    tv_device: TVDevice
    network: Network
    controller: UniFiController


@dataclass(frozen=True, slots=True)
class GuestPairingResult:
    guest_session: GuestSession
    room: Room


class GuestPairingService:
    def __init__(
        self,
        session: AsyncSession,
        *,
        max_attempts: int = 5,
        attempt_window: timedelta = timedelta(minutes=5),
        session_duration: timedelta = timedelta(hours=4),
    ) -> None:
        self.session = session
        self.max_attempts = max_attempts
        self.attempt_window = attempt_window
        self.session_duration = session_duration
        self.audit_service = AuditService(session)

    async def get_portal_context(
        self,
        qr_token: str,
        *,
        now: datetime | None = None,
        lock: bool = False,
    ) -> GuestPairingContext:
        pairing = await PairingService(self.session).lookup_qr_token(
            qr_token=qr_token,
            now=now,
            lock=lock,
        )
        guest_session = pairing.guest_session
        room = await self.session.get(Room, guest_session.room_id)
        tv_device = await self.session.get(TVDevice, guest_session.tv_device_id)
        if room is None or not room.enabled:
            raise PairingValidationError("This room is not available")
        active_tv_statuses = {
            TVDeviceStatus.PROVISIONED,
            TVDeviceStatus.ONLINE,
            TVDeviceStatus.OFFLINE,
        }
        if tv_device is None or tv_device.status not in active_tv_statuses:
            raise PairingValidationError("This TV is not available")

        network = await self.session.get(Network, room.network_id)
        if network is None:
            raise EntityNotFoundError(f"Network {room.network_id} was not found")
        controller = await self.session.get(
            UniFiController,
            network.unifi_controller_id,
        )
        if controller is None:
            raise EntityNotFoundError(
                f"UniFi controller {network.unifi_controller_id} was not found"
            )
        return GuestPairingContext(
            pairing=pairing,
            room=room,
            tv_device=tv_device,
            network=network,
            controller=controller,
        )

    async def pair(
        self,
        *,
        qr_token: str,
        pin: str,
        guest_ip: str,
        user_agent: str | None,
        client_factory: GuestUniFiClientFactory,
        now: datetime | None = None,
    ) -> GuestPairingResult:
        pairing_time = now or datetime.now(UTC)
        context = await self.get_portal_context(
            qr_token,
            now=pairing_time,
            lock=True,
        )
        await self._enforce_rate_limit(
            guest_session=context.pairing.guest_session,
            guest_ip=guest_ip,
            now=pairing_time,
        )
        if not PairingService.verify_pin(
            pin,
            context.pairing.pairing_code.code_hash,
        ):
            await self._record_failed_attempt(
                guest_session=context.pairing.guest_session,
                guest_ip=guest_ip,
                reason="invalid_pin",
            )
            raise PairingValidationError("Invalid PIN")

        client = client_factory(context.controller)
        try:
            unifi_user = await client.find_user_by_ip(guest_ip)
            guest_client = await self._upsert_guest_client(
                context=context,
                unifi_user=unifi_user,
                guest_ip=guest_ip,
                user_agent=user_agent,
                now=pairing_time,
            )
            unifi_user_id = self._required_string(unifi_user, "_id")
            site_id = self._optional_string(unifi_user.get("site_id"))
            site_id = site_id or context.controller.site

            await NetworkOverrideService(
                self.session,
                unifi_client=client,
            ).apply_guest_override(
                guest_session=context.pairing.guest_session,
                guest_client_id=guest_client.id,
                unifi_controller_id=context.controller.id,
                unifi_user_id=unifi_user_id,
                to_network_id=context.network.id,
                to_unifi_network_id=context.network.unifi_network_id,
                site_id=site_id,
                previous_override_enabled=self._optional_bool(
                    unifi_user.get("virtual_network_override_enabled")
                ),
                previous_override_id=self._optional_string(
                    unifi_user.get("virtual_network_override_id")
                ),
                actor_type="guest",
                actor_id=str(guest_client.id),
            )
        finally:
            await client.aclose()

        await PairingService(self.session).consume_validated_pairing(
            context.pairing,
            now=pairing_time,
        )
        session_service = GuestSessionService(self.session)
        await session_service.mark_paired(
            context.pairing.guest_session,
            guest_client_id=guest_client.id,
            now=pairing_time,
        )
        context.pairing.guest_session.expires_at = pairing_time + self.session_duration
        await session_service.mark_casting_instructions(
            context.pairing.guest_session,
            now=pairing_time,
        )
        await self.audit_service.create_event(
            property_id=context.room.property_id,
            actor_type="guest",
            actor_id=str(guest_client.id),
            event_type="guest.paired",
            entity_type="guest_session",
            entity_id=context.pairing.guest_session.id,
            ip_address=guest_ip,
            metadata={
                "room_id": str(context.room.id),
                "tv_device_id": str(context.tv_device.id),
            },
        )
        return GuestPairingResult(
            guest_session=context.pairing.guest_session,
            room=context.room,
        )

    async def release(
        self,
        *,
        session_token: str,
        client_factory: GuestUniFiClientFactory,
    ) -> bool:
        guest_session = await PairingService(self.session).find_session_by_qr_token(
            session_token
        )
        room = await self.session.get(Room, guest_session.room_id)
        if room is None:
            raise EntityNotFoundError(f"Room {guest_session.room_id} was not found")
        network = await self.session.get(Network, room.network_id)
        if network is None:
            raise EntityNotFoundError(f"Network {room.network_id} was not found")
        controller = await self.session.get(
            UniFiController,
            network.unifi_controller_id,
        )
        if controller is None:
            raise EntityNotFoundError(
                f"UniFi controller {network.unifi_controller_id} was not found"
            )

        client = client_factory(controller)
        try:
            override_service = NetworkOverrideService(
                self.session,
                unifi_client=client,
            )
            return await GuestSessionService(
                self.session,
                override_service=override_service,
            ).release_session(
                guest_session,
                site_id=controller.site,
                actor_type="guest",
                actor_id=(
                    str(guest_session.guest_client_id)
                    if guest_session.guest_client_id
                    else None
                ),
                reason="guest_requested",
            )
        finally:
            await client.aclose()

    async def _enforce_rate_limit(
        self,
        *,
        guest_session: GuestSession,
        guest_ip: str,
        now: datetime,
    ) -> None:
        cutoff = now - self.attempt_window
        result = await self.session.execute(
            select(func.count())
            .select_from(AuditEvent)
            .where(
                AuditEvent.event_type == PAIR_FAILURE_EVENT,
                AuditEvent.entity_id == guest_session.id,
                AuditEvent.ip_address == guest_ip,
                AuditEvent.created_at >= cutoff,
            )
        )
        attempt_count = int(result.scalar_one())
        if attempt_count >= self.max_attempts:
            await self.audit_service.create_event(
                property_id=guest_session.property_id,
                actor_type="guest",
                event_type="guest.pair.rate_limited",
                entity_type="guest_session",
                entity_id=guest_session.id,
                ip_address=guest_ip,
            )
            raise PairingRateLimitError(int(self.attempt_window.total_seconds()))

    async def _record_failed_attempt(
        self,
        *,
        guest_session: GuestSession,
        guest_ip: str,
        reason: str,
    ) -> None:
        await self.audit_service.create_event(
            property_id=guest_session.property_id,
            actor_type="guest",
            event_type=PAIR_FAILURE_EVENT,
            entity_type="guest_session",
            entity_id=guest_session.id,
            ip_address=guest_ip,
            metadata={"reason": reason},
        )

    async def _upsert_guest_client(
        self,
        *,
        context: GuestPairingContext,
        unifi_user: dict[str, Any],
        guest_ip: str,
        user_agent: str | None,
        now: datetime,
    ) -> GuestClient:
        unifi_user_id = self._required_string(unifi_user, "_id")
        mac = self._optional_string(unifi_user.get("mac"))
        identity_filters = [GuestClient.unifi_user_id == unifi_user_id]
        if mac is not None:
            identity_filters.append(GuestClient.mac == mac)

        result = await self.session.execute(
            select(GuestClient)
            .where(
                GuestClient.unifi_controller_id == context.controller.id,
                or_(*identity_filters),
            )
            .with_for_update()
        )
        guest_client = next(iter(result.scalars().all()), None)
        if guest_client is None:
            guest_client = GuestClient(
                property_id=context.room.property_id,
                unifi_controller_id=context.controller.id,
                unifi_user_id=unifi_user_id,
                mac=mac,
                last_ip=guest_ip,
                hostname=self._optional_string(unifi_user.get("hostname")),
                user_agent=(user_agent[:500] if user_agent else None),
                first_seen_at=now,
                last_seen_at=now,
            )
            self.session.add(guest_client)
        else:
            guest_client.unifi_user_id = unifi_user_id
            guest_client.mac = mac or guest_client.mac
            guest_client.last_ip = guest_ip
            guest_client.hostname = (
                self._optional_string(unifi_user.get("hostname"))
                or guest_client.hostname
            )
            guest_client.user_agent = (
                user_agent[:500] if user_agent else guest_client.user_agent
            )
            guest_client.last_seen_at = now
        await self.session.flush()
        return guest_client

    @staticmethod
    def _required_string(record: dict[str, Any], key: str) -> str:
        value = record.get(key)
        if not isinstance(value, str) or not value:
            raise UniFiMalformedResponseError(f"UniFi client record is missing {key}")
        return value

    @staticmethod
    def _optional_string(value: Any) -> str | None:
        return value if isinstance(value, str) and value else None

    @staticmethod
    def _optional_bool(value: Any) -> bool | None:
        return value if isinstance(value, bool) else None
