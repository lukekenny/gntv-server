from collections.abc import Mapping
from types import TracebackType
from typing import Any, Self
from urllib.parse import quote

import httpx

type UniFiRecord = dict[str, Any]


class UniFiError(Exception):
    """Base exception for UniFi integration failures."""


class UniFiAuthenticationError(UniFiError):
    """The UniFi controller rejected the supplied credentials."""


class UniFiConnectivityError(UniFiError):
    """The UniFi controller could not be reached."""


class UniFiNotFoundError(UniFiError):
    """The requested UniFi resource was not found."""


class UniFiAPIError(UniFiError):
    """UniFi returned a valid envelope with an unsuccessful result."""

    def __init__(self, rc: str) -> None:
        self.rc = rc
        super().__init__(f"UniFi returned unsuccessful meta.rc: {rc}")


class UniFiMalformedResponseError(UniFiError):
    """The UniFi response was not valid JSON or had an unexpected shape."""


class UniFiUnexpectedStatusError(UniFiError):
    """UniFi returned an HTTP status not handled by a more specific error."""

    def __init__(self, status_code: int) -> None:
        self.status_code = status_code
        super().__init__(f"UniFi returned unexpected HTTP status {status_code}")


class UniFiClient:
    def __init__(
        self,
        *,
        base_url: str,
        site: str,
        api_key: str,
        verify_tls: bool = True,
        timeout: float | httpx.Timeout = 10.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.site = site
        self._client = httpx.AsyncClient(
            base_url=f"{base_url.rstrip('/')}/",
            headers={
                "X-API-Key": api_key,
                "Accept": "application/json",
            },
            verify=verify_tls,
            timeout=timeout,
            transport=transport,
        )

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._client.aclose()

    async def list_networks(self) -> list[UniFiRecord]:
        return await self._request("GET", self._rest_path("networkconf"))

    async def list_users(self) -> list[UniFiRecord]:
        return await self._request("GET", self._rest_path("user"))

    async def get_user(self, user_id: str) -> UniFiRecord:
        users = await self._request(
            "GET",
            self._rest_path("user", quote(user_id, safe="")),
        )
        if not users:
            raise UniFiNotFoundError(f"UniFi user {user_id!r} was not found")
        return users[0]

    async def find_user_by_ip(self, ip_address: str) -> UniFiRecord:
        for user in await self.list_users():
            if user.get("last_ip") == ip_address:
                return user

        raise UniFiNotFoundError(f"No UniFi user found for IP address {ip_address}")

    async def apply_network_override(
        self,
        user_id: str,
        network_id: str,
        site_id: str,
    ) -> UniFiRecord | None:
        payload = {
            "virtual_network_override_enabled": True,
            "virtual_network_override_id": network_id,
            "site_id": site_id,
        }
        return await self._update_user(user_id, payload)

    async def clear_network_override(
        self,
        user_id: str,
        site_id: str,
    ) -> UniFiRecord | None:
        payload = {
            "virtual_network_override_enabled": False,
            "virtual_network_override_id": "",
            "site_id": site_id,
        }
        return await self._update_user(user_id, payload)

    def _rest_path(self, resource: str, resource_id: str | None = None) -> str:
        path = f"api/s/{quote(self.site, safe='')}/rest/{resource}"
        if resource_id is not None:
            path = f"{path}/{resource_id}"
        return path

    async def _update_user(
        self,
        user_id: str,
        payload: dict[str, Any],
    ) -> UniFiRecord | None:
        users = await self._request(
            "PUT",
            self._rest_path("user", quote(user_id, safe="")),
            json=payload,
        )
        return users[0] if users else None

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
    ) -> list[UniFiRecord]:
        headers = {"Content-Type": "application/json"} if method == "PUT" else None

        try:
            response = await self._client.request(
                method,
                path,
                headers=headers,
                json=json,
            )
        except httpx.RequestError as exc:
            raise UniFiConnectivityError("Unable to communicate with UniFi") from exc

        if response.status_code in {401, 403}:
            raise UniFiAuthenticationError(
                f"UniFi rejected the request with HTTP {response.status_code}"
            )
        if response.status_code == 404:
            raise UniFiNotFoundError("UniFi resource was not found")
        if not response.is_success:
            raise UniFiUnexpectedStatusError(response.status_code)

        return self._parse_response(response)

    @staticmethod
    def _parse_response(response: httpx.Response) -> list[UniFiRecord]:
        try:
            payload = response.json()
        except ValueError as exc:
            raise UniFiMalformedResponseError(
                "UniFi response was not valid JSON"
            ) from exc

        if not isinstance(payload, Mapping):
            raise UniFiMalformedResponseError("UniFi response must be an object")

        meta = payload.get("meta")
        if not isinstance(meta, Mapping):
            raise UniFiMalformedResponseError("UniFi response meta must be an object")

        rc = meta.get("rc")
        if not isinstance(rc, str):
            raise UniFiMalformedResponseError("UniFi response meta.rc must be a string")
        if rc != "ok":
            raise UniFiAPIError(rc)

        data = payload.get("data")
        if not isinstance(data, list):
            raise UniFiMalformedResponseError("UniFi response data must be a list")

        records: list[UniFiRecord] = []
        for item in data:
            if not isinstance(item, Mapping):
                raise UniFiMalformedResponseError(
                    "UniFi response data entries must be objects"
                )
            records.append(dict(item))

        return records
