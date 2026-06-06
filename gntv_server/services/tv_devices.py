from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from gntv_server.models import TVDevice
from gntv_server.models.enums import TVDeviceStatus
from gntv_server.services.exceptions import EntityNotFoundError
from gntv_server.services.security import hash_opaque_token


class TVDeviceService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create_enrollment(
        self,
        *,
        room_id: UUID,
        name: str,
        provisioning_token: str,
        adb_serial: str | None = None,
    ) -> TVDevice:
        device = TVDevice(
            room_id=room_id,
            name=name,
            adb_serial=adb_serial,
            provisioning_token_hash=hash_opaque_token(provisioning_token),
            status=TVDeviceStatus.ENROLLING,
        )
        self.session.add(device)
        await self.session.flush()
        return device

    async def get_device(self, device_id: UUID) -> TVDevice:
        device = await self.session.get(TVDevice, device_id)
        if device is None:
            raise EntityNotFoundError(f"TV device {device_id} was not found")
        return device

    async def list_devices(
        self,
        *,
        room_id: UUID | None = None,
        status: TVDeviceStatus | None = None,
    ) -> list[TVDevice]:
        statement: Select[tuple[TVDevice]] = select(TVDevice).order_by(TVDevice.name)
        if room_id is not None:
            statement = statement.where(TVDevice.room_id == room_id)
        if status is not None:
            statement = statement.where(TVDevice.status == status)

        result = await self.session.execute(statement)
        return list(result.scalars().all())

    async def update_heartbeat(
        self,
        device: TVDevice,
        *,
        last_ip: str | None = None,
        app_version: str | None = None,
        heartbeat_at: datetime | None = None,
    ) -> TVDevice:
        if last_ip is not None:
            device.last_ip = last_ip
        if app_version is not None:
            device.app_version = app_version
        device.last_heartbeat_at = heartbeat_at or datetime.now(UTC)
        device.status = TVDeviceStatus.ONLINE
        await self.session.flush()
        return device

    async def assign_to_room(self, device: TVDevice, room_id: UUID) -> TVDevice:
        device.room_id = room_id
        await self.session.flush()
        return device

    async def mark_status(
        self,
        device: TVDevice,
        status: TVDeviceStatus,
    ) -> TVDevice:
        device.status = status
        await self.session.flush()
        return device
