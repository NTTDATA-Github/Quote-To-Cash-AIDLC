"""Identity: resolving who's calling (tenant + roles) from a request's headers.

`IdentityProvider` is the port; `HeaderStubIdentityProvider` (local dev — trusts a
gateway-provided header) and `CognitoIdentityProvider` (verifies a real JWT against
Cognito's JWKS) are the two adapters, selected by profile in `composition.py` — same
pattern as every other cross-cutting concern (secrets, event store, ERP adapters).
"""

from __future__ import annotations

from .cognito import CognitoIdentityProvider
from .entra import EntraIdentityProvider
from .provider import HeaderStubIdentityProvider, IdentityProvider, Principal

__all__ = [
    "CognitoIdentityProvider",
    "EntraIdentityProvider",
    "HeaderStubIdentityProvider",
    "IdentityProvider",
    "Principal",
]
