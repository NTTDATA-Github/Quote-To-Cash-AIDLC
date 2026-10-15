from __future__ import annotations

import pytest
from src.shared.net import UnsafeUrl, validate_outbound_url


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/orders",
        "http://localhost/orders",
        "http://10.1.2.3/orders",
        "http://172.16.0.5/orders",
        "http://192.168.1.1/orders",
        "http://169.254.169.254/latest/meta-data/",  # cloud metadata endpoint
        "http://[::1]/orders",
        "http://0.0.0.0/orders",
    ],
)
def test_rejects_non_public_addresses(url: str) -> None:
    with pytest.raises(UnsafeUrl):
        validate_outbound_url(url)


def test_rejects_unsupported_scheme() -> None:
    with pytest.raises(UnsafeUrl, match="scheme"):
        validate_outbound_url("ftp://8.8.8.8/orders")


def test_rejects_missing_host() -> None:
    with pytest.raises(UnsafeUrl, match="no host"):
        validate_outbound_url("http:///orders")


def test_rejects_unresolvable_host() -> None:
    with pytest.raises(UnsafeUrl, match="cannot resolve"):
        validate_outbound_url("http://this-host-does-not-exist.invalid/orders")


def test_allows_a_public_ip_literal() -> None:
    # A numeric IP needs no DNS lookup, so this is safe and deterministic offline.
    validate_outbound_url("https://8.8.8.8/orders")
