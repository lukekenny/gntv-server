import os
import secrets
from collections.abc import Callable
from typing import Annotated

from fastapi import Depends, HTTPException, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from gntv_server.core.config import Settings, get_settings
from gntv_server.db.session import get_db_session
from gntv_server.integrations.unifi import UniFiClient
from gntv_server.models import TVDevice, UniFiController
from gntv_server.services.exceptions import (
    DeviceAuthenticationError,
    ServiceConfigurationError,
)
from gntv_server.services.tv_devices import TVDeviceService

UniFiClientFactory = Callable[[UniFiController], UniFiClient]

bearer_scheme = HTTPBearer(auto_error=False)


def require_admin(
    credentials: Annotated[
        HTTPAuthorizationCredentials | None,
        Security(bearer_scheme),
    ],
    settings: Annotated[Settings, Depends(get_settings)],
) -> str:
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Admin bearer token is required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not settings.admin_token:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Admin authentication is not configured",
        )
    if not secrets.compare_digest(credentials.credentials, settings.admin_token):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid admin bearer token",
        )
    return "admin"


async def require_tv_device(
    credentials: Annotated[
        HTTPAuthorizationCredentials | None,
        Security(bearer_scheme),
    ],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> TVDevice:
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="TV device bearer token is required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        return await TVDeviceService(session).authenticate_device(
            credentials.credentials
        )
    except DeviceAuthenticationError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid TV device bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


def get_unifi_client_factory(
    settings: Annotated[Settings, Depends(get_settings)],
) -> UniFiClientFactory:
    def create_client(controller: UniFiController) -> UniFiClient:
        if controller.api_key_ref == "UNIFI_API_KEY":
            api_key = settings.unifi_api_key
        else:
            api_key = os.environ.get(controller.api_key_ref, "")
        if not api_key:
            raise ServiceConfigurationError(
                f"UniFi API key reference {controller.api_key_ref!r} is not configured"
            )

        return UniFiClient(
            base_url=controller.base_url,
            site=controller.site,
            api_key=api_key,
            verify_tls=controller.verify_tls,
        )

    return create_client
