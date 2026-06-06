from datetime import timedelta
from pathlib import Path
from typing import Annotated

from fastapi import (
    APIRouter,
    Depends,
    Form,
    HTTPException,
    Request,
    status,
)
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession

from gntv_server.api.client_ip import get_guest_ip
from gntv_server.api.dependencies import (
    UniFiClientFactory,
    get_unifi_client_factory,
)
from gntv_server.core.config import Settings, get_settings
from gntv_server.db.session import get_db_session
from gntv_server.integrations.unifi import UniFiError, UniFiNotFoundError
from gntv_server.schemas.admin import APIResponse
from gntv_server.schemas.guest import (
    GuestPairRequest,
    GuestPairResult,
    GuestReleaseRequest,
    GuestReleaseResult,
)
from gntv_server.services.exceptions import (
    EntityNotFoundError,
    PairingExpiredError,
    PairingRateLimitError,
    PairingValidationError,
    ServiceConfigurationError,
)
from gntv_server.services.guest_pairing import GuestPairingService

router = APIRouter(tags=["guest"])
templates = Jinja2Templates(
    directory=Path(__file__).resolve().parent.parent / "templates"
)

Session = Annotated[AsyncSession, Depends(get_db_session)]
ClientFactory = Annotated[UniFiClientFactory, Depends(get_unifi_client_factory)]
GuestIP = Annotated[str, Depends(get_guest_ip)]


def get_guest_pairing_service(
    session: Session,
    settings: Annotated[Settings, Depends(get_settings)],
) -> GuestPairingService:
    return GuestPairingService(
        session,
        max_attempts=settings.guest_pin_max_attempts,
        attempt_window=timedelta(seconds=settings.guest_pin_window_seconds),
        session_duration=timedelta(seconds=settings.guest_session_duration_seconds),
    )


GuestService = Annotated[
    GuestPairingService,
    Depends(get_guest_pairing_service),
]


def _template_context(
    *,
    request: Request,
    state: str,
    room_display_name: str | None = None,
    qr_token: str | None = None,
    error_message: str | None = None,
) -> dict[str, object]:
    return {
        "request": request,
        "state": state,
        "room_display_name": room_display_name,
        "qr_token": qr_token,
        "error_message": error_message,
    }


@router.get("/join", response_class=HTMLResponse)
async def join_page(
    request: Request,
    service: GuestService,
    t: str,
) -> HTMLResponse:
    try:
        context = await service.get_portal_context(t)
    except PairingExpiredError:
        return templates.TemplateResponse(
            request=request,
            name="join.html",
            context=_template_context(
                request=request,
                state="error",
                error_message="This pairing code has expired. Refresh the TV screen.",
            ),
            status_code=status.HTTP_410_GONE,
        )
    except PairingValidationError:
        return templates.TemplateResponse(
            request=request,
            name="join.html",
            context=_template_context(
                request=request,
                state="error",
                error_message="This pairing link is invalid or no longer available.",
            ),
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    except EntityNotFoundError:
        return templates.TemplateResponse(
            request=request,
            name="join.html",
            context=_template_context(
                request=request,
                state="error",
                error_message="This room is temporarily unavailable.",
            ),
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    return templates.TemplateResponse(
        request=request,
        name="join.html",
        context=_template_context(
            request=request,
            state="form",
            room_display_name=context.room.display_name,
            qr_token=t,
        ),
    )


@router.post("/join", response_class=HTMLResponse)
async def submit_join_page(
    request: Request,
    session: Session,
    service: GuestService,
    client_factory: ClientFactory,
    guest_ip: GuestIP,
    t: Annotated[str, Form(min_length=1)],
    pin: Annotated[str, Form(pattern=r"^\d{4}$")],
) -> HTMLResponse:
    try:
        result = await service.pair(
            qr_token=t,
            pin=pin,
            guest_ip=guest_ip,
            user_agent=request.headers.get("user-agent"),
            client_factory=client_factory,
        )
    except PairingRateLimitError as exc:
        await session.commit()
        return templates.TemplateResponse(
            request=request,
            name="join.html",
            context=_template_context(
                request=request,
                state="form",
                qr_token=t,
                error_message="Too many attempts. Wait a few minutes and try again.",
            ),
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            headers={"Retry-After": str(exc.retry_after_seconds)},
        )
    except (PairingExpiredError, PairingValidationError):
        await session.commit()
        return templates.TemplateResponse(
            request=request,
            name="join.html",
            context=_template_context(
                request=request,
                state="form",
                qr_token=t,
                error_message="The PIN is incorrect or has expired.",
            ),
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    except UniFiNotFoundError:
        await session.commit()
        return templates.TemplateResponse(
            request=request,
            name="join.html",
            context=_template_context(
                request=request,
                state="form",
                qr_token=t,
                error_message=(
                    "Your device was not found on guest Wi-Fi. Check your "
                    "connection and try again."
                ),
            ),
            status_code=status.HTTP_409_CONFLICT,
        )
    except UniFiError:
        await session.commit()
        return templates.TemplateResponse(
            request=request,
            name="join.html",
            context=_template_context(
                request=request,
                state="error",
                error_message="Pairing is temporarily unavailable.",
            ),
            status_code=status.HTTP_502_BAD_GATEWAY,
        )
    except (ServiceConfigurationError, EntityNotFoundError):
        await session.rollback()
        return templates.TemplateResponse(
            request=request,
            name="join.html",
            context=_template_context(
                request=request,
                state="error",
                error_message="Pairing is temporarily unavailable.",
            ),
            status_code=status.HTTP_502_BAD_GATEWAY,
        )

    await session.commit()
    return templates.TemplateResponse(
        request=request,
        name="join.html",
        context=_template_context(
            request=request,
            state="success",
            room_display_name=result.room.display_name,
        ),
    )


@router.post(
    "/api/guest/pair",
    response_model=APIResponse[GuestPairResult],
)
async def pair_guest(
    payload: GuestPairRequest,
    request: Request,
    session: Session,
    service: GuestService,
    client_factory: ClientFactory,
    guest_ip: GuestIP,
) -> APIResponse[GuestPairResult]:
    try:
        result = await service.pair(
            qr_token=payload.qr_token.get_secret_value(),
            pin=payload.pin.get_secret_value(),
            guest_ip=guest_ip,
            user_agent=request.headers.get("user-agent"),
            client_factory=client_factory,
        )
    except PairingRateLimitError as exc:
        await session.commit()
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many PIN attempts",
            headers={"Retry-After": str(exc.retry_after_seconds)},
        ) from exc
    except PairingExpiredError as exc:
        await session.commit()
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="Pairing credentials have expired",
        ) from exc
    except PairingValidationError as exc:
        await session.commit()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid pairing credentials",
        ) from exc
    except UniFiNotFoundError as exc:
        await session.commit()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Guest device was not found on guest Wi-Fi",
        ) from exc
    except UniFiError as exc:
        await session.commit()
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Pairing is temporarily unavailable",
        ) from exc
    except (ServiceConfigurationError, EntityNotFoundError) as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Pairing is temporarily unavailable",
        ) from exc

    await session.commit()
    guest_session = result.guest_session
    return APIResponse(
        data=GuestPairResult(
            status="paired",
            session_id=guest_session.id,
            room_display_name=result.room.display_name,
            message=(
                "You are connected. Open a Cast-enabled app and select the room TV."
            ),
            expires_at=guest_session.expires_at,
        )
    )


@router.post(
    "/api/guest/release",
    response_model=APIResponse[GuestReleaseResult],
)
async def release_guest(
    payload: GuestReleaseRequest,
    session: Session,
    service: GuestService,
    client_factory: ClientFactory,
) -> APIResponse[GuestReleaseResult]:
    try:
        released = await service.release(
            session_token=payload.session_token.get_secret_value(),
            client_factory=client_factory,
        )
    except PairingValidationError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid session token",
        ) from exc
    except UniFiError as exc:
        await session.commit()
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Release is temporarily unavailable",
        ) from exc
    except (ServiceConfigurationError, EntityNotFoundError) as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Release is temporarily unavailable",
        ) from exc

    await session.commit()
    return APIResponse(
        data=GuestReleaseResult(
            status="released" if released else "already_released",
            released=released,
        )
    )
