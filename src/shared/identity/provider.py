"""The `IdentityProvider` port + the local-dev stub adapter.

`authenticate` takes request headers (not a bearer token directly) so both adapters have
the same shape even though they read different headers — the header-parsing detail stays
inside the adapter, not leaked into the API layer that calls this port.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from collections.abc import Mapping


@dataclass(frozen=True)
class Principal:
    tenant_id: str
    roles: tuple[str, ...]


class IdentityProvider(Protocol):
    def authenticate(self, headers: Mapping[str, str]) -> Principal | None:
        """`None` means "reject this request" (missing/invalid credentials). Some
        implementations (the local stub) never return `None` — see below."""
        ...


class HeaderStubIdentityProvider:
    """Local dev only: trusts `x-tenant-id`/`x-roles` headers outright, no verification.

    Deliberately permissive (defaults to `tnt_demo` rather than rejecting) — it's a
    development convenience, not a security boundary. `KeycloakIdentityProvider` is the
    one that actually rejects unauthenticated requests.
    """

    def authenticate(self, headers: Mapping[str, str]) -> Principal | None:
        tenant = headers.get("x-tenant-id", "tnt_demo")
        roles = tuple(r for r in headers.get("x-roles", "").split(",") if r)
        return Principal(tenant_id=tenant, roles=roles)
