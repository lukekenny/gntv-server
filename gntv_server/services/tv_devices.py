from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from gntv_server.models import TVDevice
from gntv_server.models.enums import TVDeviceStatus
from gntv_server.services.exceptions import (
    DeviceAuthenticationError,
    EntityNotFoundError,
    ProvisioningValidationError,
)
from gntv_server.services.security import (
    generate_opaque_token,
    hash_opaque_token,
    verify_opaque_token,
)


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

    async def register_device(
        self,
        *,
        provisioning_token: str,
        android_id: str | None = None,
        model: str | None = None,
        app_version: str | None = None,
    ) -> tuple[TVDevice, str]:
        provisioning_token_hash = hash_opaque_token(provisioning_token)
        result = await self.session.execute(
            select(TVDevice)
            .where(
                TVDevice.provisioning_token_hash == provisioning_token_hash,
                TVDevice.status == TVDeviceStatus.ENROLLING,
            )
            .with_for_update()
        )
        matches = list(result.scalars().all())
        if len(matches) != 1 or not verify_opaque_token(
            provisioning_token,
            matches[0].provisioning_token_hash or "",
        ):
            raise ProvisioningValidationError("Invalid provisioning token")

        device = matches[0]
        device_token = generate_opaque_token()
        device.device_token_hash = hash_opaque_token(device_token)
        device.provisioning_token_hash = None
        device.android_id = android_id
        device.model = model
        device.app_version = app_version
        device.status = TVDeviceStatus.PROVISIONED
        await self.session.flush()
        return device, device_token

    async def authenticate_device(self, device_token: str) -> TVDevice:
        device_token_hash = hash_opaque_token(device_token)
        result = await self.session.execute(
            select(TVDevice).where(
                TVDevice.device_token_hash == device_token_hash,
                TVDevice.status != TVDeviceStatus.DISABLED,
            )
        )
        matches = list(result.scalars().all())
        if len(matches) != 1 or not verify_opaque_token(
            device_token,
            matches[0].device_token_hash or "",
        ):
            raise DeviceAuthenticationError("Invalid TV device token")
        return matches[0]

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
        foreground: bool | None = None,
        screen_mode: str | None = None,
        heartbeat_at: datetime | None = None,
    ) -> TVDevice:
        if last_ip is not None:
            device.last_ip = last_ip
        if app_version is not None:
            device.app_version = app_version
        if foreground is not None:
            device.foreground = foreground
        if screen_mode is not None:
            device.screen_mode = screen_mode
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
