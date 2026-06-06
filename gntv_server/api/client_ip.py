from ipaddress import ip_address, ip_network
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status

from gntv_server.core.config import Settings, get_settings


def resolve_client_ip(request: Request, settings: Settings) -> str | None:
    if request.client is None:
        return None
    try:
        peer_ip = ip_address(request.client.host)
    except ValueError:
        return None

    if not settings.trust_proxy_headers:
        return str(peer_ip)

    trusted_networks = []
    for value in settings.trusted_proxy_cidrs.split(","):
        value = value.strip()
        if not value:
            continue
        try:
            trusted_networks.append(ip_network(value, strict=False))
        except ValueError:
            continue

    def is_trusted(value: object) -> bool:
        return any(value in network for network in trusted_networks)

    if not is_trusted(peer_ip):
        return str(peer_ip)

    forwarded_for = request.headers.get("x-forwarded-for")
    if not forwarded_for:
        return str(peer_ip)

    try:
        forwarded_chain = [
            ip_address(value.strip()) for value in forwarded_for.split(",")
        ]
    except ValueError:
        return str(peer_ip)

    for address in reversed([*forwarded_chain, peer_ip]):
        if not is_trusted(address):
            return str(address)
    return str(forwarded_chain[0]) if forwarded_chain else str(peer_ip)


def get_guest_ip(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
) -> str:
    guest_ip = resolve_client_ip(request, settings)
    if guest_ip is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unable to determine guest IP address",
        )
    return guest_ip
