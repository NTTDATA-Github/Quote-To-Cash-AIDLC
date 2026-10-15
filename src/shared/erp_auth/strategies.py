"""Auth strategies — declarative only, by design.

Each strategy turns one resolved secret into headers/query params. None of them do a
handshake, sign a request, or redirect a human anywhere. That rules out, on purpose:
- OAuth1 / HMAC request signing (e.g. NetSuite's TBA: every request needs a fresh
  nonce+timestamp signature computed from `consumer_secret`+`token_secret` — there is no
  "header to attach").
- OAuth2 authorization-code (QuickBooks, Xero, Salesforce, NetSuite's newer OAuth2) —
  needs a browser redirect to the ERP's own login/consent screen, not a credentials form.
- Session-cookie login, SOAP WS-Security, mutual TLS.

Those need their own strategy each, added when a real ERP actually requires it (same
registry, additive) — not pre-built speculatively. Until then, the always-available
fallback is the existing manual sample-file upload (`MappingService.submit_job`), which
covers any ERP regardless of how exotic its auth is.
"""

from __future__ import annotations

import base64
from typing import Protocol

from .types import AppliedAuth, AuthConfig, AuthType


class AuthStrategy(Protocol):
    def apply(self, config: AuthConfig, secret: str | None) -> AppliedAuth: ...


class _NoAuth:
    def apply(self, config: AuthConfig, secret: str | None) -> AppliedAuth:
        return AppliedAuth()


class _ApiKeyHeader:
    def apply(self, config: AuthConfig, secret: str | None) -> AppliedAuth:
        if not secret:
            raise ValueError("API_KEY_HEADER auth requires a secret (the API key)")
        header_name = config.params.get("header_name") or "X-API-Key"
        return AppliedAuth(headers={header_name: secret})


class _Basic:
    def apply(self, config: AuthConfig, secret: str | None) -> AppliedAuth:
        if secret is None:
            raise ValueError("BASIC auth requires a secret (the password)")
        username = config.params.get("username", "")
        token = base64.b64encode(f"{username}:{secret}".encode()).decode()
        return AppliedAuth(headers={"Authorization": f"Basic {token}"})


class _BearerToken:
    def apply(self, config: AuthConfig, secret: str | None) -> AppliedAuth:
        if not secret:
            raise ValueError("BEARER_TOKEN auth requires a secret (the token)")
        return AppliedAuth(headers={"Authorization": f"Bearer {secret}"})


AUTH_STRATEGIES: dict[AuthType, AuthStrategy] = {
    AuthType.NONE: _NoAuth(),
    AuthType.API_KEY_HEADER: _ApiKeyHeader(),
    AuthType.BASIC: _Basic(),
    AuthType.BEARER_TOKEN: _BearerToken(),
}


def apply_auth(config: AuthConfig, secret: str | None) -> AppliedAuth:
    strategy = AUTH_STRATEGIES.get(config.auth_type)
    if strategy is None:
        raise ValueError(f"no auth strategy registered for {config.auth_type!r}")
    return strategy.apply(config, secret)
