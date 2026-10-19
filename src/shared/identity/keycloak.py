"""Keycloak JWT verification — the real Azure `IdentityProvider`, replacing
`EntraIdentityProvider` until a real Entra External ID tenant exists (ADR-0023: Entra app
creation is blocked by `Authorization_RequestDenied` in the sandbox; Keycloak is
self-administered, so it needs no tenant-admin permission at all).

Single token shape, like Entra's: a direct-grant login always returns an access token
with `tenant_id` and `roles` claims (realm protocol mappers — see
`keycloak-realm-export.json`), both flat.

Keycloak access tokens don't reliably carry this client's id in `aud` unless an explicit
audience mapper is configured (we don't configure one) — `azp` (authorized party) is the
claim Keycloak always sets to the client that requested the token, so that's what's
checked instead.
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


class KeycloakIdentityProvider:
    def __init__(
        self,
        *,
        issuer: str,
        client_id: str,
        jwk_client: PyJWKClient | None = None,
    ) -> None:
        self._issuer = issuer.rstrip("/")
        self._client_id = client_id
        jwks_url = f"{self._issuer}/protocol/openid-connect/certs"
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
                options={"verify_aud": False},
            )
        except jwt.PyJWTError as exc:
            log.info("token rejected: %s", exc)
            return None

        if claims.get("azp") != self._client_id:
            log.info("token rejected: azp mismatch (sub=%s)", claims.get("sub"))
            return None

        tenant_id = claims.get("tenant_id")
        if not tenant_id:
            log.info("token rejected: no tenant_id claim (sub=%s)", claims.get("sub"))
            return None
        roles = tuple(claims.get("roles", []))
        return Principal(tenant_id=tenant_id, roles=roles)
