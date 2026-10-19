"""Entra External ID JWT verification (ADR-0023).

Single token shape: the SPA (MSAL) always presents an
access token with `aud` = this app's client id and `roles` = the app roles assigned to the
signed-in user — there is no separate
"ID token" concept here, and this project has no machine-to-machine caller on the Azure
path yet, so there's no second shape to handle.

`tenant_claim_name` is a constructor argument, not a hardcoded guess: Entra External ID's
per-user `tenant_id` custom attribute surfaces as a claim named by the portal-configured
attribute (something like `extension_<appid>_tenant_id`) — see ADR-0023's "no clean
Terraform story yet" note. Pin the real name once Phase 1's manual tenant setup is done.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import jwt
from jwt import PyJWKClient

from .provider import Principal

if TYPE_CHECKING:
    from collections.abc import Mapping

log = logging.getLogger(__name__)


class EntraIdentityProvider:
    def __init__(
        self,
        *,
        tenant_id: str,
        client_id: str,
        tenant_claim_name: str,
        issuer: str | None = None,
        jwks_url: str | None = None,
        jwk_client: PyJWKClient | None = None,
    ) -> None:
        self._client_id = client_id
        self._tenant_claim_name = tenant_claim_name
        self._issuer = issuer or f"https://login.microsoftonline.com/{tenant_id}/v2.0"
        jwks_url = jwks_url or f"https://login.microsoftonline.com/{tenant_id}/discovery/v2.0/keys"
        self._jwks = jwk_client or PyJWKClient(jwks_url)

    def authenticate(self, headers: Mapping[str, str]) -> Principal | None:
        auth_header = headers.get("authorization", "")
        if not auth_header.startswith("Bearer "):
            return None
        token = auth_header[len("Bearer ") :]

        try:
            signing_key = self._jwks.get_signing_key_from_jwt(token)
            claims = jwt.decode(
                token,
                signing_key.key,
                algorithms=["RS256"],
                issuer=self._issuer,
                audience=self._client_id,
            )
        except jwt.PyJWTError as exc:
            log.info("token rejected: %s", exc)
            return None

        tenant_id = claims.get(self._tenant_claim_name)
        if not tenant_id:
            log.info(
                "token rejected: no %r claim (sub=%s)", self._tenant_claim_name, claims.get("sub")
            )
            return None
        roles = tuple(claims.get("roles", []))
        return Principal(tenant_id=tenant_id, roles=roles)
