"""Cognito JWT verification (JWKS) — the production `IdentityProvider`.

Handles two different Cognito token shapes, both signed the same way (same issuer, same
JWKS) but carrying tenant/role information completely differently:

- **ID token** (`token_use=id`) — issued by a *user* login (`USER_PASSWORD_AUTH` and
  similar). Carries `custom:tenant_id` (a Cognito custom attribute on the user) and
  `cognito:groups` (the user's group memberships). Has an `aud` claim.
- **Access token** (`token_use=access`) — issued by `client_credentials` (machine-to-
  machine: a backend calling us directly, no human involved) as well as by user logins
  (which this project doesn't use the access token for). There's no user, so there's no
  `custom:tenant_id`/`cognito:groups` to read — tenant and roles instead come from OAuth
  **scopes** granted to that app client: `{resource_server_id}/tenant.<tenant_id>`
  (exactly one, required) and `{resource_server_id}/role.<ROLE>` (zero or more).
  **Cognito access tokens have no `aud` claim at all** (a real quirk, not a bug here) —
  `client_id` is the equivalent field, checked manually instead of via PyJWT's `audience=`.

Signature is checked against Cognito's published JWKS (`PyJWKClient` fetches + caches
keys). Any failure — bad signature, wrong issuer/audience, expired, missing/ambiguous
tenant scope, wrong token type — is treated identically: reject (`None`), never partially
trust a token that failed one check.
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


def _same_loopback(left: str, right: str) -> bool:
    """`localhost` and `127.0.0.1` are the same machine. Windows often resets one of them."""

    def norm(url: str) -> str:
        return url.replace("://localhost", "://127.0.0.1")

    return norm(left) == norm(right)


def issuer_url(*, aws_endpoint_url: str | None, aws_region: str, user_pool_id: str) -> str:
    """floci and real AWS use the same path, different host — same pattern as every
    other AWS-backed port in this project (secrets, messaging)."""
    if aws_endpoint_url:
        return f"{aws_endpoint_url.rstrip('/')}/{user_pool_id}"
    return f"https://cognito-idp.{aws_region}.amazonaws.com/{user_pool_id}"


class CognitoIdentityProvider:
    def __init__(
        self,
        *,
        user_pool_id: str,
        client_id: str,
        issuer: str,
        resource_server_id: str = "o2c",
        jwk_client: PyJWKClient | None = None,
    ) -> None:
        self._client_id = client_id
        self._issuer = issuer
        self._resource_server_id = resource_server_id
        # `localhost` on Windows often resolves to IPv6 and the local emulator only
        # accepts IPv4, which resets the JWKS fetch. The token's issuer string stays
        # whatever Cognito minted.
        jwks_url = f"{issuer}/.well-known/jwks.json".replace("://localhost:", "://127.0.0.1:")
        self._jwks = jwk_client or PyJWKClient(jwks_url)

    def authenticate(self, headers: Mapping[str, str]) -> Principal | None:
        auth_header = headers.get("authorization", "")
        if not auth_header.startswith("Bearer "):
            return None
        token = auth_header[len("Bearer ") :]

        try:
            signing_key = self._jwks.get_signing_key_from_jwt(token)
            # No `audience=` here: ID and access tokens verify it differently (aud vs
            # client_id) — done manually below, per token_use. PyJWT otherwise auto-
            # rejects any token that HAS an `aud` claim when `audience=` isn't given
            # (its fail-safe default), so `verify_aud` must be turned off explicitly.
            token_issuer = jwt.decode(token, options={"verify_signature": False}).get("iss", "")
            issuer = (
                token_issuer
                if isinstance(token_issuer, str) and _same_loopback(token_issuer, self._issuer)
                else self._issuer
            )
            claims = jwt.decode(
                token,
                signing_key.key,
                algorithms=["RS256"],
                issuer=issuer,
                options={"verify_aud": False},
            )
        except jwt.PyJWTError as exc:
            log.info("token rejected: %s", exc)
            return None

        token_use = claims.get("token_use")
        if token_use == "id":
            return self._id_token_principal(claims)
        if token_use == "access":
            return self._access_token_principal(claims)
        log.info("token rejected: unrecognized token_use=%r", token_use)
        return None

    def _id_token_principal(self, claims: dict) -> Principal | None:
        if claims.get("aud") != self._client_id:
            log.info("ID token rejected: aud mismatch (sub=%s)", claims.get("sub"))
            return None
        tenant_id = claims.get("custom:tenant_id")
        if not tenant_id:
            log.info("ID token rejected: no custom:tenant_id claim (sub=%s)", claims.get("sub"))
            return None
        roles = tuple(claims.get("cognito:groups", []))
        return Principal(tenant_id=tenant_id, roles=roles)

    def _access_token_principal(self, claims: dict) -> Principal | None:
        if claims.get("client_id") != self._client_id:
            log.info("access token rejected: client_id mismatch")
            return None

        scopes = claims.get("scope", "").split()
        prefix = f"{self._resource_server_id}/"
        tenant_scopes = [
            s[len(prefix) + len("tenant.") :] for s in scopes if s.startswith(f"{prefix}tenant.")
        ]
        if len(tenant_scopes) != 1:
            log.info(
                "access token rejected: expected exactly one tenant scope, found %d",
                len(tenant_scopes),
            )
            return None
        roles = tuple(
            s[len(prefix) + len("role.") :] for s in scopes if s.startswith(f"{prefix}role.")
        )
        return Principal(tenant_id=tenant_scopes[0], roles=roles)
