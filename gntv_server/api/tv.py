from ipaddress import ip_address
from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from gntv_server.api.dependencies import require_tv_device
from gntv_server.core.config import Settings, get_settings
from gntv_server.db.session import get_db_session
from gntv_server.models import TVDevice
from gntv_server.schemas.admin import APIResponse
from gntv_server.schemas.tv import (
    TVBrandingConfig,
    TVCastStateRequest,
    TVCastStateResult,
    TVConfigResult,
    TVHeartbeatRequest,
    TVHeartbeatResult,
    TVPairingConfig,
    TVRegisterRequest,
    TVRegisterResult,
    TVRoomConfig,
    TVScreenConfig,
)
from gntv_server.services.audit import AuditService
from gntv_server.services.exceptions import (
    EntityNotFoundError,
    ProvisioningValidationError,
)
from gntv_server.services.tv_app import TV_POLL_AFTER_SECONDS, TVAppService
from gntv_server.services.tv_devices import TVDeviceService

router = APIRouter(prefix="/api/tv", tags=["tv"])

Session = Annotated[AsyncSession, Depends(get_db_session)]
AuthenticatedTV = Annotated[TVDevice, Depends(require_tv_device)]
AppSettings = Annotated[Settings, Depends(get_settings)]


def _request_ip(request: Request) -> str | None:
    if request.client is None:
        return None
    try:
        return str(ip_address(request.client.host))
    except ValueError:
        return None


@router.post(
    "/register",
    response_model=APIResponse[TVRegisterResult],
)
async def register_tv_device(
    payload: TVRegisterRequest,
    request: Request,
    session: Session,
) -> APIResponse[TVRegisterResult]:
    service = TVDeviceService(session)
    try:
        device, device_token = await service.register_device(
            provisioning_token=payload.provisioning_token.get_secret_value(),
            android_id=payload.device_info.android_id,
            model=payload.device_info.model,
            app_version=payload.device_info.app_version,
        )
    except ProvisioningValidationError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid provisioning token",
        ) from exc

    try:
        context = await TVAppService(session).get_context(device)
    except EntityNotFoundError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    await AuditService(session).create_event(
        actor_type="tv_device",
        actor_id=str(device.id),
        event_type="tv_device.registered",
        property_id=context.room.property_id,
        entity_type="tv_device",
        entity_id=device.id,
        ip_address=_request_ip(request),
    )
    await session.commit()
    return APIResponse(
        data=TVRegisterResult(
            tv_device_id=device.id,
            device_token=device_token,
        )
    )


@router.get("/config", response_model=APIResponse[TVConfigResult])
async def get_tv_config(
    device: AuthenticatedTV,
    settings: AppSettings,
    session: Session,
) -> APIResponse[TVConfigResult]:
    try:
        config = await TVAppService(session).build_config(device)
    except EntityNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc

    await session.commit()
    qr_token = quote(config.pairing.qr_token, safe="")
    qr_url = f"{str(settings.public_base_url).rstrip('/')}/join?t={qr_token}"
    return APIResponse(
        data=TVConfigResult(
            tv_device_id=device.id,
            room=TVRoomConfig(
                id=config.context.room.id,
                display_name=config.context.room.display_name,
            ),
            branding=TVBrandingConfig(
                **TVAppService.branding_values(config.context.branding)
            ),
            pairing=TVPairingConfig(
                pin=config.pairing.pin,
                qr_url=qr_url,
                expires_at=config.pairing.expires_at,
            ),
            screen=TVScreenConfig(mode=config.screen_mode),
            poll_after_seconds=config.poll_after_seconds,
        )
    )


@router.post("/heartbeat", response_model=APIResponse[TVHeartbeatResult])
async def heartbeat(
    payload: TVHeartbeatRequest,
    device: AuthenticatedTV,
    session: Session,
) -> APIResponse[TVHeartbeatResult]:
    await TVDeviceService(session).update_heartbeat(
        device,
        last_ip=str(payload.local_ip) if payload.local_ip is not None else None,
        app_version=payload.app_version,
        foreground=payload.foreground,
        screen_mode=payload.screen_mode.value if payload.screen_mode else None,
    )
    desired_screen_mode = await TVAppService(session).desired_screen_mode(device)
    await session.commit()
    return APIResponse(
        data=TVHeartbeatResult(
            desired_screen_mode=desired_screen_mode,
            poll_after_seconds=TV_POLL_AFTER_SECONDS,
        )
    )


@router.post("/cast-state", response_model=APIResponse[TVCastStateResult])
async def report_cast_state(
    payload: TVCastStateRequest,
    request: Request,
    device: AuthenticatedTV,
    session: Session,
) -> APIResponse[TVCastStateResult]:
    await TVAppService(session).record_cast_state(
        device,
        state=payload.state.value,
        ip_address=_request_ip(request),
    )
    await session.commit()
    return APIResponse(data=TVCastStateResult(accepted=True))
