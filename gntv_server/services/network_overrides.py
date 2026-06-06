from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from gntv_server.models import GuestSession, NetworkOverride
from gntv_server.models.enums import OverrideState
from gntv_server.services.audit import AuditService


class UniFiOverrideClient(Protocol):
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


class NetworkOverrideService:
    def __init__(
        self,
        session: AsyncSession,
        *,
        unifi_client: UniFiOverrideClient,
        audit_service: AuditService | None = None,
    ) -> None:
        self.session = session
        self.unifi_client = unifi_client
        self.audit_service = audit_service or AuditService(session)

    async def apply_guest_override(
        self,
        *,
        guest_session: GuestSession,
        guest_client_id: UUID,
        unifi_controller_id: UUID,
        unifi_user_id: str,
        to_network_id: UUID,
        to_unifi_network_id: str,
        site_id: str,
        previous_override_enabled: bool | None = None,
        previous_override_id: str | None = None,
        actor_type: str = "system",
        actor_id: str | None = None,
    ) -> NetworkOverride:
        override = NetworkOverride(
            guest_session_id=guest_session.id,
            guest_client_id=guest_client_id,
            unifi_controller_id=unifi_controller_id,
            unifi_user_id=unifi_user_id,
            to_network_id=to_network_id,
            to_unifi_network_id=to_unifi_network_id,
            previous_override_enabled=previous_override_enabled,
            previous_override_id=previous_override_id,
            state=OverrideState.PENDING,
        )
        self.session.add(override)
        await self.session.flush()

        try:
            await self.unifi_client.apply_network_override(
                unifi_user_id,
                to_unifi_network_id,
                site_id,
            )
        except Exception as exc:
            override.state = OverrideState.FAILED
            override.last_error = type(exc).__name__
            await self._audit_override(
                override,
                property_id=guest_session.property_id,
                event_type="unifi.override.apply_failed",
                actor_type=actor_type,
                actor_id=actor_id,
                metadata={"error_type": type(exc).__name__},
            )
            await self.session.flush()
            raise

        override.state = OverrideState.APPLIED
        override.applied_at = datetime.now(UTC)
        override.last_error = None
        await self._audit_override(
            override,
            property_id=guest_session.property_id,
            event_type="unifi.override.applied",
            actor_type=actor_type,
            actor_id=actor_id,
            metadata={
                "guest_session_id": str(guest_session.id),
                "guest_client_id": str(guest_client_id),
                "unifi_network_id": to_unifi_network_id,
            },
        )
        await self.session.flush()
        return override

    async def clear_guest_override(
        self,
        override: NetworkOverride,
        *,
        site_id: str,
        property_id: UUID | None = None,
        actor_type: str = "system",
        actor_id: str | None = None,
        reason: str,
    ) -> bool:
        if override.state == OverrideState.RELEASED:
            return False

        override.state = OverrideState.RELEASE_PENDING
        await self.session.flush()

        try:
            await self.unifi_client.clear_network_override(
                override.unifi_user_id,
                site_id,
            )
        except Exception as exc:
            override.state = OverrideState.FAILED
            override.last_error = type(exc).__name__
            await self._audit_override(
                override,
                property_id=property_id,
                event_type="unifi.override.clear_failed",
                actor_type=actor_type,
                actor_id=actor_id,
                metadata={
                    "reason": reason,
                    "error_type": type(exc).__name__,
                },
            )
            await self.session.flush()
            raise

        override.state = OverrideState.RELEASED
        override.released_at = datetime.now(UTC)
        override.last_error = None
        await self._audit_override(
            override,
            property_id=property_id,
            event_type="unifi.override.cleared",
            actor_type=actor_type,
            actor_id=actor_id,
            metadata={
                "reason": reason,
                "clear_policy": "disable_override",
                "virtual_network_override_enabled": False,
                "virtual_network_override_id": "",
            },
        )
        await self.session.flush()
        return True

    async def clear_guest_override_for_session(
        self,
        guest_session: GuestSession,
        *,
        site_id: str,
        actor_type: str = "system",
        actor_id: str | None = None,
        reason: str,
    ) -> bool:
        result = await self.session.execute(
            select(NetworkOverride)
            .where(
                NetworkOverride.guest_session_id == guest_session.id,
                NetworkOverride.state != OverrideState.RELEASED,
            )
            .order_by(NetworkOverride.created_at)
        )
        overrides = list(result.scalars().all())
        cleared = False
        for override in overrides:
            did_clear = await self.clear_guest_override(
                override,
                site_id=site_id,
                property_id=guest_session.property_id,
                actor_type=actor_type,
                actor_id=actor_id,
                reason=reason,
            )
            cleared = did_clear or cleared
        return cleared

    async def clear_guest_overrides_for_client(
        self,
        *,
        guest_client_id: UUID,
        site_id: str,
        property_id: UUID | None,
        actor_type: str = "system",
        actor_id: str | None = None,
        reason: str,
    ) -> int:
        result = await self.session.execute(
            select(NetworkOverride)
            .where(
                NetworkOverride.guest_client_id == guest_client_id,
                NetworkOverride.state != OverrideState.RELEASED,
            )
            .order_by(NetworkOverride.created_at)
        )
        overrides = list(result.scalars().all())
        cleared_count = 0
        for override in overrides:
            if await self.clear_guest_override(
                override,
                site_id=site_id,
                property_id=property_id,
                actor_type=actor_type,
                actor_id=actor_id,
                reason=reason,
            ):
                cleared_count += 1
        return cleared_count

    async def _audit_override(
        self,
        override: NetworkOverride,
        *,
        property_id: UUID | None,
        event_type: str,
        actor_type: str,
        actor_id: str | None,
        metadata: dict[str, object],
    ) -> None:
        await self.audit_service.create_event(
            property_id=property_id,
            actor_type=actor_type,
            actor_id=actor_id,
            event_type=event_type,
            entity_type="network_override",
            entity_id=override.id,
            metadata=metadata,
        )
