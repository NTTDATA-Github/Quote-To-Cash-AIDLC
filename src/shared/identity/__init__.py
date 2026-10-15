"""Identity: resolving who's calling (tenant + roles) from a request's headers.

`IdentityProvider` is the port; `HeaderStubIdentityProvider` (local dev — trusts a
gateway-provided header), `CognitoIdentityProvider` (AWS), `EntraIdentityProvider`
(Azure, once a real Entra External ID tenant exists) and `KeycloakIdentityProvider`
(Azure, self-hosted — the real one in use today) are the adapters, selected by profile in
`composition.py` — same pattern as every other cross-cutting concern (secrets, event
store, ERP adapters).
"""

from __future__ import annotations

from .cognito import CognitoIdentityProvider
from .entra import EntraIdentityProvider
from .keycloak import KeycloakIdentityProvider
from .provider import HeaderStubIdentityProvider, IdentityProvider, Principal

__all__ = [
    "CognitoIdentityProvider",
    "EntraIdentityProvider",
    "HeaderStubIdentityProvider",
    "IdentityProvider",
    "KeycloakIdentityProvider",
    "Principal",
]
