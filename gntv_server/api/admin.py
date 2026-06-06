from ipaddress import ip_address
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from gntv_server.api.dependencies import (
    UniFiClientFactory,
    get_unifi_client_factory,
    require_admin,
)
from gntv_server.db.session import get_db_session
from gntv_server.integrations.unifi import UniFiError
from gntv_server.models.enums import TVDeviceStatus
from gntv_server.schemas.admin import (
    APIResponse,
    AuditEventRead,
    NetworkSyncResult,
    PropertyCreate,
    PropertyRead,
    RoomCreate,
    RoomRead,
    RoomUpdate,
    TVDeviceRead,
    UniFiControllerCreate,
    UniFiControllerRead,
    UniFiTestResult,
)
from gntv_server.services.admin import PropertyService, UniFiControllerService
from gntv_server.services.audit import AuditService
from gntv_server.services.exceptions import (
    EntityNotFoundError,
    ServiceConfigurationError,
)
from gntv_server.services.rooms import RoomService
from gntv_server.services.tv_devices import TVDeviceService

router = APIRouter(
    prefix="/api/admin",
    tags=["admin"],
    dependencies=[Depends(require_admin)],
)

Session = Annotated[AsyncSession, Depends(get_db_session)]
ClientFactory = Annotated[UniFiClientFactory, Depends(get_unifi_client_factory)]


def _request_ip(request: Request) -> str | None:
    if request.client is None:
        return None
    try:
        return str(ip_address(request.client.host))
    except ValueError:
        return None


async def _commit(session: AsyncSession) -> None:
    try:
        await session.commit()
    except IntegrityError as exc:
        await _raise_conflict(session, exc)


async def _raise_conflict(
    session: AsyncSession,
    exc: IntegrityError,
) -> None:
    await session.rollback()
    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail="The requested resource conflicts with an existing record",
    ) from exc


def _not_found(exc: EntityNotFoundError) -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


@router.get("/properties", response_model=APIResponse[list[PropertyRead]])
async def list_properties(session: Session) -> APIResponse[list[PropertyRead]]:
    properties = await PropertyService(session).list_properties()
    return APIResponse(data=properties)


@router.post(
    "/properties",
    response_model=APIResponse[PropertyRead],
    status_code=status.HTTP_201_CREATED,
)
async def create_property(
    payload: PropertyCreate,
    request: Request,
    session: Session,
) -> APIResponse[PropertyRead]:
    try:
        property_ = await PropertyService(session).create_property(
            **payload.model_dump()
        )
        await AuditService(session).create_event(
            actor_type="admin",
            actor_id="admin",
            event_type="property.created",
            property_id=property_.id,
            entity_type="property",
            entity_id=property_.id,
            ip_address=_request_ip(request),
        )
    except IntegrityError as exc:
        await _raise_conflict(session, exc)
    await _commit(session)
    return APIResponse(data=property_)


@router.get(
    "/unifi/controllers",
    response_model=APIResponse[list[UniFiControllerRead]],
)
async def list_unifi_controllers(
    session: Session,
    property_id: UUID | None = None,
) -> APIResponse[list[UniFiControllerRead]]:
    controllers = await UniFiControllerService(session).list_controllers(
        property_id=property_id
    )
    return APIResponse(data=controllers)


@router.post(
    "/unifi/controllers",
    response_model=APIResponse[UniFiControllerRead],
    status_code=status.HTTP_201_CREATED,
)
async def create_unifi_controller(
    payload: UniFiControllerCreate,
    request: Request,
    session: Session,
) -> APIResponse[UniFiControllerRead]:
    service = UniFiControllerService(session)
    try:
        controller = await service.create_controller(
            property_id=payload.property_id,
            name=payload.name,
            base_url=str(payload.base_url),
            site=payload.site,
            api_key_ref=payload.api_key_ref,
            verify_tls=payload.verify_tls,
        )
    except EntityNotFoundError as exc:
        raise _not_found(exc) from exc
    except IntegrityError as exc:
        await _raise_conflict(session, exc)

    try:
        await AuditService(session).create_event(
            actor_type="admin",
            actor_id="admin",
            event_type="unifi.controller.created",
            property_id=controller.property_id,
            entity_type="unifi_controller",
            entity_id=controller.id,
            ip_address=_request_ip(request),
            metadata={"api_key_ref": controller.api_key_ref},
        )
    except IntegrityError as exc:
        await _raise_conflict(session, exc)
    await _commit(session)
    return APIResponse(data=controller)


@router.post(
    "/unifi/controllers/{controller_id}/test",
    response_model=APIResponse[UniFiTestResult],
)
async def test_unifi_controller(
    controller_id: UUID,
    request: Request,
    session: Session,
    client_factory: ClientFactory,
) -> APIResponse[UniFiTestResult]:
    service = UniFiControllerService(session)
    try:
        controller = await service.get_controller(controller_id)
    except EntityNotFoundError as exc:
        raise _not_found(exc) from exc

    client = None
    try:
        client = client_factory(controller)
        network_count, user_count = await service.test_controller(client)
    except (ServiceConfigurationError, UniFiError) as exc:
        await AuditService(session).create_event(
            actor_type="admin",
            actor_id="admin",
            event_type="unifi.controller.test_failed",
            property_id=controller.property_id,
            entity_type="unifi_controller",
            entity_id=controller.id,
            ip_address=_request_ip(request),
            metadata={"error_type": type(exc).__name__},
        )
        await _commit(session)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="UniFi controller test failed",
        ) from exc
    finally:
        if client is not None:
            await client.aclose()

    await AuditService(session).create_event(
        actor_type="admin",
        actor_id="admin",
        event_type="unifi.controller.tested",
        property_id=controller.property_id,
        entity_type="unifi_controller",
        entity_id=controller.id,
        ip_address=_request_ip(request),
    )
    await _commit(session)
    return APIResponse(
        data=UniFiTestResult(
            status="ok",
            network_count=network_count,
            user_count=user_count,
        )
    )


@router.post(
    "/unifi/controllers/{controller_id}/sync-networks",
    response_model=APIResponse[NetworkSyncResult],
)
async def sync_unifi_networks(
    controller_id: UUID,
    request: Request,
    session: Session,
    client_factory: ClientFactory,
) -> APIResponse[NetworkSyncResult]:
    service = UniFiControllerService(session)
    try:
        controller = await service.get_controller(controller_id)
    except EntityNotFoundError as exc:
        raise _not_found(exc) from exc

    client = None
    try:
        client = client_factory(controller)
        created, updated, total = await service.sync_networks(
            controller=controller,
            client=client,
        )
    except IntegrityError as exc:
        await _raise_conflict(session, exc)
    except (ServiceConfigurationError, UniFiError, ValueError) as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="UniFi network sync failed",
        ) from exc
    finally:
        if client is not None:
            await client.aclose()

    await AuditService(session).create_event(
        actor_type="admin",
        actor_id="admin",
        event_type="unifi.networks.synced",
        property_id=controller.property_id,
        entity_type="unifi_controller",
        entity_id=controller.id,
        ip_address=_request_ip(request),
        metadata={"created": created, "updated": updated, "total": total},
    )
    await _commit(session)
    return APIResponse(
        data=NetworkSyncResult(created=created, updated=updated, total=total)
    )


@router.get("/rooms", response_model=APIResponse[list[RoomRead]])
async def list_rooms(
    session: Session,
    property_id: UUID | None = None,
    enabled: bool | None = None,
) -> APIResponse[list[RoomRead]]:
    rooms = await RoomService(session).list_rooms(
        property_id=property_id,
        enabled=enabled,
    )
    return APIResponse(data=rooms)


@router.post(
    "/rooms",
    response_model=APIResponse[RoomRead],
    status_code=status.HTTP_201_CREATED,
)
async def create_room(
    payload: RoomCreate,
    request: Request,
    session: Session,
) -> APIResponse[RoomRead]:
    try:
        room = await RoomService(session).create_room(**payload.model_dump())
    except EntityNotFoundError as exc:
        raise _not_found(exc) from exc
    except IntegrityError as exc:
        await _raise_conflict(session, exc)

    try:
        await AuditService(session).create_event(
            actor_type="admin",
            actor_id="admin",
            event_type="room.created",
            property_id=room.property_id,
            entity_type="room",
            entity_id=room.id,
            ip_address=_request_ip(request),
        )
    except IntegrityError as exc:
        await _raise_conflict(session, exc)
    await _commit(session)
    return APIResponse(data=room)


@router.get("/rooms/{room_id}", response_model=APIResponse[RoomRead])
async def get_room(room_id: UUID, session: Session) -> APIResponse[RoomRead]:
    try:
        room = await RoomService(session).get_room(room_id)
    except EntityNotFoundError as exc:
        raise _not_found(exc) from exc
    return APIResponse(data=room)


@router.put("/rooms/{room_id}", response_model=APIResponse[RoomRead])
async def update_room(
    room_id: UUID,
    payload: RoomUpdate,
    request: Request,
    session: Session,
) -> APIResponse[RoomRead]:
    service = RoomService(session)
    try:
        room = await service.get_room(room_id)
        room = await service.update_room(
            room,
            **payload.model_dump(exclude_unset=True),
        )
    except EntityNotFoundError as exc:
        raise _not_found(exc) from exc
    except IntegrityError as exc:
        await _raise_conflict(session, exc)

    try:
        await AuditService(session).create_event(
            actor_type="admin",
            actor_id="admin",
            event_type="room.updated",
            property_id=room.property_id,
            entity_type="room",
            entity_id=room.id,
            ip_address=_request_ip(request),
            metadata={"fields": sorted(payload.model_fields_set)},
        )
    except IntegrityError as exc:
        await _raise_conflict(session, exc)
    await _commit(session)
    return APIResponse(data=room)


@router.delete("/rooms/{room_id}", response_model=APIResponse[RoomRead])
async def delete_room(
    room_id: UUID,
    request: Request,
    session: Session,
) -> APIResponse[RoomRead]:
    service = RoomService(session)
    try:
        room = await service.get_room(room_id)
    except EntityNotFoundError as exc:
        raise _not_found(exc) from exc

    room = await service.soft_disable_room(room)
    await AuditService(session).create_event(
        actor_type="admin",
        actor_id="admin",
        event_type="room.disabled",
        property_id=room.property_id,
        entity_type="room",
        entity_id=room.id,
        ip_address=_request_ip(request),
    )
    await _commit(session)
    return APIResponse(data=room)


@router.get("/tv-devices", response_model=APIResponse[list[TVDeviceRead]])
async def list_tv_devices(
    session: Session,
    room_id: UUID | None = None,
    device_status: Annotated[TVDeviceStatus | None, Query(alias="status")] = None,
) -> APIResponse[list[TVDeviceRead]]:
    devices = await TVDeviceService(session).list_devices(
        room_id=room_id,
        status=device_status,
    )
    return APIResponse(data=devices)


@router.get(
    "/tv-devices/{tv_device_id}",
    response_model=APIResponse[TVDeviceRead],
)
async def get_tv_device(
    tv_device_id: UUID,
    session: Session,
) -> APIResponse[TVDeviceRead]:
    try:
        device = await TVDeviceService(session).get_device(tv_device_id)
    except EntityNotFoundError as exc:
        raise _not_found(exc) from exc
    return APIResponse(data=device)


@router.get("/audit-events", response_model=APIResponse[list[AuditEventRead]])
async def list_audit_events(
    session: Session,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 50,
    property_id: UUID | None = None,
    event_type: str | None = None,
) -> APIResponse[list[AuditEventRead]]:
    events, total = await AuditService(session).list_events(
        page=page,
        page_size=page_size,
        property_id=property_id,
        event_type=event_type,
    )
    return APIResponse(
        data=events,
        meta={
            "page": page,
            "page_size": page_size,
            "total": total,
        },
    )
