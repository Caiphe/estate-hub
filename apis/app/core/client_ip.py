import ipaddress
from collections.abc import Sequence

from pydantic import IPvAnyNetwork
from starlette.requests import Request

type IPAddress = ipaddress.IPv4Address | ipaddress.IPv6Address


def _parse(value: str) -> IPAddress | None:
    try:
        address = ipaddress.ip_address(value.strip())
    except ValueError:
        return None
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
        return address.ipv4_mapped
    return address


def _trusted(address: IPAddress, proxies: Sequence[IPvAnyNetwork]) -> bool:
    return any(address in network for network in proxies)


def client_ip(request: Request, trusted_proxies: Sequence[IPvAnyNetwork]) -> str | None:
    """The address of the client that sent the request.

    The TCP peer is the client unless it is a configured trusted proxy. Only then is
    ``X-Forwarded-For`` read, from the right, skipping further trusted proxies; the first
    untrusted address is the client. Entries a client prepends itself are never reached.
    """
    peer = _parse(request.client.host) if request.client else None
    if peer is None or not _trusted(peer, trusted_proxies):
        return str(peer) if peer else None

    forwarded = ",".join(request.headers.getlist("x-forwarded-for"))
    hops = [hop for hop in (_parse(part) for part in forwarded.split(",")) if hop is not None]
    for hop in reversed(hops):
        if not _trusted(hop, trusted_proxies):
            return str(hop)
    # Every hop is a trusted proxy, or the header was absent or malformed.
    return str(hops[0]) if hops else str(peer)
