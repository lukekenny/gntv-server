import os
import secrets
from collections.abc import Callable
from typing import Annotated

from fastapi import Depends, HTTPException, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from gntv_server.core.config import Settings, get_settings
from gntv_server.integrations.unifi import UniFiClient
from gntv_server.models import UniFiController
from gntv_server.services.exceptions import ServiceConfigurationError

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
