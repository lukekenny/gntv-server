from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import UUID

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from gntv_server.models import Network, Property, UniFiController
from gntv_server.services.exceptions import EntityNotFoundError


class UniFiAdminClient(Protocol):
    async def list_networks(self) -> list[dict[str, Any]]: ...

    async def list_users(self) -> list[dict[str, Any]]: ...


class PropertyService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create_property(
        self,
        *,
        name: str,
        slug: str,
        timezone: str,
    ) -> Property:
        property_ = Property(name=name, slug=slug, timezone=timezone)
        self.session.add(property_)
        await self.session.flush()
        return property_

    async def list_properties(self) -> list[Property]:
        result = await self.session.execute(select(Property).order_by(Property.name))
        return list(result.scalars().all())


class UniFiControllerService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create_controller(
        self,
        *,
        property_id: UUID,
        name: str,
        base_url: str,
        site: str,
        api_key_ref: str,
        verify_tls: bool,
    ) -> UniFiController:
        if await self.session.get(Property, property_id) is None:
            raise EntityNotFoundError(f"Property {property_id} was not found")

        controller = UniFiController(
            property_id=property_id,
            name=name,
            base_url=base_url.rstrip("/"),
            site=site,
            api_key_ref=api_key_ref,
            verify_tls=verify_tls,
        )
        self.session.add(controller)
        await self.session.flush()
        return controller

    async def get_controller(self, controller_id: UUID) -> UniFiController:
        controller = await self.session.get(UniFiController, controller_id)
        if controller is None:
            raise EntityNotFoundError(f"UniFi controller {controller_id} was not found")
        return controller

    async def list_controllers(
        self,
        *,
        property_id: UUID | None = None,
    ) -> list[UniFiController]:
        statement: Select[tuple[UniFiController]] = select(UniFiController).order_by(
            UniFiController.name
        )
        if property_id is not None:
            statement = statement.where(UniFiController.property_id == property_id)
        result = await self.session.execute(statement)
        return list(result.scalars().all())

    @staticmethod
    async def test_controller(
        client: UniFiAdminClient,
    ) -> tuple[int, int]:
        networks = await client.list_networks()
        users = await client.list_users()
        return len(networks), len(users)

    async def sync_networks(
        self,
        *,
        controller: UniFiController,
        client: UniFiAdminClient,
    ) -> tuple[int, int, int]:
        remote_networks = await client.list_networks()
        result = await self.session.execute(
            select(Network).where(Network.unifi_controller_id == controller.id)
        )
        existing = {
            network.unifi_network_id: network for network in result.scalars().all()
        }

        created = 0
        updated = 0
        synced_at = datetime.now(UTC)
        for record in remote_networks:
            unifi_network_id = record.get("_id")
            name = record.get("name")
            if not isinstance(unifi_network_id, str) or not unifi_network_id:
                raise ValueError("UniFi network is missing a valid _id")
            if not isinstance(name, str) or not name:
                raise ValueError("UniFi network is missing a valid name")

            network = existing.get(unifi_network_id)
            if network is None:
                network = Network(
                    property_id=controller.property_id,
                    unifi_controller_id=controller.id,
                    unifi_network_id=unifi_network_id,
                    name=name,
                    last_synced_at=synced_at,
                )
                self.session.add(network)
                existing[unifi_network_id] = network
                created += 1
            else:
                updated += 1

            network.name = name
            network.vlan = self._optional_int(record.get("vlan"))
            network.ip_subnet = self._optional_string(record.get("ip_subnet"))
            network.mdns_enabled = self._optional_bool(record.get("mdns_enabled"))
            network.network_isolation_enabled = self._optional_bool(
                record.get("network_isolation_enabled")
            )
            network.raw = dict(record)
            network.last_synced_at = synced_at

        await self.session.flush()
        return created, updated, len(remote_networks)

    @staticmethod
    def _optional_string(value: Any) -> str | None:
        return value if isinstance(value, str) and value else None

    @staticmethod
    def _optional_bool(value: Any) -> bool | None:
        return value if isinstance(value, bool) else None

    @staticmethod
    def _optional_int(value: Any) -> int | None:
        if isinstance(value, bool):
            return None
        if isinstance(value, int):
            return value
        if isinstance(value, str) and value.isdigit():
            return int(value)
        return None
