import json
from collections.abc import Callable

import httpx
import pytest

from gntv_server.integrations.unifi import (
    UniFiAPIError,
    UniFiAuthenticationError,
    UniFiClient,
    UniFiConnectivityError,
    UniFiMalformedResponseError,
    UniFiNotFoundError,
    UniFiUnexpectedStatusError,
)

BASE_URL = "https://unifi.test/proxy/network"
SITE = "default"


def make_client(handler: Callable[[httpx.Request], httpx.Response]) -> UniFiClient:
    return UniFiClient(
        base_url=BASE_URL,
        site=SITE,
        api_key="not-a-secret",
        verify_tls=False,
        timeout=2.0,
        transport=httpx.MockTransport(handler),
    )


def ok_response(data: list[dict[str, object]]) -> httpx.Response:
    return httpx.Response(200, json={"meta": {"rc": "ok"}, "data": data})


@pytest.mark.anyio
async def test_list_networks() -> None:
    networks = [{"_id": "network-1", "name": "Room 101"}]

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.path == ("/proxy/network/api/s/default/rest/networkconf")
        assert request.headers["X-API-Key"] == "not-a-secret"
        assert request.headers["Accept"] == "application/json"
        return ok_response(networks)

    async with make_client(handler) as client:
        assert await client.list_networks() == networks


@pytest.mark.anyio
async def test_list_users() -> None:
    users = [{"_id": "user-1", "last_ip": "192.0.2.10"}]

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/proxy/network/api/s/default/rest/user"
        return ok_response(users)

    async with make_client(handler) as client:
        assert await client.list_users() == users


@pytest.mark.anyio
async def test_find_user_by_last_ip() -> None:
    users = [
        {"_id": "user-1", "last_ip": "192.0.2.10"},
        {"_id": "user-2", "last_ip": "192.0.2.20"},
    ]

    async with make_client(lambda request: ok_response(users)) as client:
        user = await client.find_user_by_ip("192.0.2.20")

    assert user["_id"] == "user-2"


@pytest.mark.anyio
async def test_find_user_by_ip_raises_when_not_found() -> None:
    users = [{"_id": "user-1", "last_ip": "192.0.2.10"}]

    async with make_client(lambda request: ok_response(users)) as client:
        with pytest.raises(UniFiNotFoundError):
            await client.find_user_by_ip("192.0.2.99")


@pytest.mark.anyio
async def test_get_user_by_id() -> None:
    user = {"_id": "user/with spaces", "last_ip": "192.0.2.10"}

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.raw_path == (
            b"/proxy/network/api/s/default/rest/user/user%2Fwith%20spaces"
        )
        return ok_response([user])

    async with make_client(handler) as client:
        assert await client.get_user("user/with spaces") == user


@pytest.mark.anyio
async def test_apply_network_override_payload() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "PUT"
        assert request.headers["Content-Type"] == "application/json"
        assert json.loads(request.content) == {
            "virtual_network_override_enabled": True,
            "virtual_network_override_id": "network-1",
            "site_id": "site-1",
        }
        return ok_response([{"_id": "user-1"}])

    async with make_client(handler) as client:
        result = await client.apply_network_override(
            "user-1",
            "network-1",
            "site-1",
        )

    assert result == {"_id": "user-1"}


@pytest.mark.anyio
async def test_clear_network_override_payload() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "PUT"
        assert json.loads(request.content) == {
            "virtual_network_override_enabled": False,
            "virtual_network_override_id": "",
            "site_id": "site-1",
        }
        return ok_response([{"_id": "user-1"}])

    async with make_client(handler) as client:
        result = await client.clear_network_override("user-1", "site-1")

    assert result == {"_id": "user-1"}


@pytest.mark.anyio
async def test_non_ok_unifi_meta_response() -> None:
    response = httpx.Response(
        200,
        json={"meta": {"rc": "error"}, "data": []},
    )

    async with make_client(lambda request: response) as client:
        with pytest.raises(UniFiAPIError) as exc_info:
            await client.list_users()

    assert exc_info.value.rc == "error"


@pytest.mark.anyio
@pytest.mark.parametrize("status_code", [401, 403])
async def test_authentication_failure(status_code: int) -> None:
    response = httpx.Response(status_code)

    async with make_client(lambda request: response) as client:
        with pytest.raises(UniFiAuthenticationError):
            await client.list_users()


@pytest.mark.anyio
@pytest.mark.parametrize(
    "error_factory",
    [
        lambda request: httpx.ReadTimeout("timed out", request=request),
        lambda request: httpx.ConnectError("connection failed", request=request),
    ],
)
async def test_timeout_and_connectivity_failures(
    error_factory: Callable[[httpx.Request], httpx.RequestError],
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise error_factory(request)

    async with make_client(handler) as client:
        with pytest.raises(UniFiConnectivityError):
            await client.list_users()


@pytest.mark.anyio
async def test_malformed_response() -> None:
    response = httpx.Response(200, content=b"not-json")

    async with make_client(lambda request: response) as client:
        with pytest.raises(UniFiMalformedResponseError):
            await client.list_users()


@pytest.mark.anyio
async def test_unexpected_http_status() -> None:
    response = httpx.Response(500)

    async with make_client(lambda request: response) as client:
        with pytest.raises(UniFiUnexpectedStatusError) as exc_info:
            await client.list_users()

    assert exc_info.value.status_code == 500
