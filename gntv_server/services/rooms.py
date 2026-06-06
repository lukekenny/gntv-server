from uuid import UUID

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from gntv_server.models import Network, Room
from gntv_server.services.exceptions import EntityNotFoundError


class RoomService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create_room(
        self,
        *,
        property_id: UUID,
        room_code: str,
        display_name: str,
        network_id: UUID,
        enabled: bool = True,
    ) -> Room:
        await self._validate_network(property_id=property_id, network_id=network_id)
        room = Room(
            property_id=property_id,
            room_code=room_code,
            display_name=display_name,
            network_id=network_id,
            enabled=enabled,
        )
        self.session.add(room)
        await self.session.flush()
        return room

    async def get_room(self, room_id: UUID) -> Room:
        room = await self.session.get(Room, room_id)
        if room is None:
            raise EntityNotFoundError(f"Room {room_id} was not found")
        return room

    async def list_rooms(
        self,
        *,
        property_id: UUID | None = None,
        enabled: bool | None = None,
    ) -> list[Room]:
        statement: Select[tuple[Room]] = select(Room).order_by(Room.room_code)
        if property_id is not None:
            statement = statement.where(Room.property_id == property_id)
        if enabled is not None:
            statement = statement.where(Room.enabled == enabled)

        result = await self.session.execute(statement)
        return list(result.scalars().all())

    async def update_room(
        self,
        room: Room,
        *,
        room_code: str | None = None,
        display_name: str | None = None,
        network_id: UUID | None = None,
        enabled: bool | None = None,
    ) -> Room:
        if room_code is not None:
            room.room_code = room_code
        if display_name is not None:
            room.display_name = display_name
        if network_id is not None:
            await self._validate_network(
                property_id=room.property_id,
                network_id=network_id,
            )
            room.network_id = network_id
        if enabled is not None:
            room.enabled = enabled

        await self.session.flush()
        return room

    async def soft_disable_room(self, room: Room) -> Room:
        room.enabled = False
        await self.session.flush()
        return room

    async def _validate_network(
        self,
        *,
        property_id: UUID,
        network_id: UUID,
    ) -> Network:
        network = await self.session.get(Network, network_id)
        if network is None or network.property_id != property_id:
            raise EntityNotFoundError(
                f"Network {network_id} was not found for property {property_id}"
            )
        return network
