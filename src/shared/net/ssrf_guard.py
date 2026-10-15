"""Blocks outbound HTTP calls to non-public network addresses.

Needed anywhere the backend dials a URL an operator supplies at request time — today,
the ERP-onboarding probe (`GenericErpProbe`). Without this, "test my ERP connection" is an
SSRF primitive against the platform's own network: a cloud metadata endpoint
(`169.254.169.254`), a VPC-internal service, or `localhost` itself. `ErpConnection.base_url`
(a real, already-vetted connection) is a separate, narrower trust boundary — this guard is
specifically for calls made on the strength of input nobody has reviewed yet.
"""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlsplit

_ALLOWED_SCHEMES = {"http", "https"}


class UnsafeUrl(ValueError):
    """The URL is malformed, or resolves to a non-public address — refuse to dial it."""


def validate_outbound_url(url: str) -> None:
    parts = urlsplit(url)
    if parts.scheme not in _ALLOWED_SCHEMES:
        raise UnsafeUrl(f"unsupported scheme {parts.scheme!r} — only http/https are allowed")
    host = parts.hostname
    if not host:
        raise UnsafeUrl("URL has no host")

    try:
        resolved = socket.getaddrinfo(host, None)
    except socket.gaierror as exc:
        raise UnsafeUrl(f"cannot resolve host {host!r}: {exc}") from exc

    for _family, _type, _proto, _canonname, sockaddr in resolved:
        ip = ipaddress.ip_address(sockaddr[0])
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
            or ip.is_unspecified
        ):
            raise UnsafeUrl(
                f"{host!r} resolves to a non-public address ({ip}) — refusing to dial it"
            )
