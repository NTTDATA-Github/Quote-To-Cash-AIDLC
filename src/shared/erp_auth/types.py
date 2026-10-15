"""Plain data shapes for outbound auth. No I/O, no secret resolution here — that's the
caller's job (e.g. `GenericErpProbe` resolves `secret_ref` via `SecretStore` before
calling `apply_auth`)."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class AuthType(str, Enum):
    """Declarative auth types a single HTTP call can satisfy — a static value turned into
    a header or query param. Anything that needs a handshake (OAuth2 client-credentials'
    token exchange, phase 1b), per-request signing (OAuth1/HMAC), or a human consent
    redirect (OAuth2 authorization-code) is a separate, later strategy — see
    `strategies.py`'s module docstring."""

    NONE = "NONE"
    API_KEY_HEADER = "API_KEY_HEADER"
    BASIC = "BASIC"
    BEARER_TOKEN = "BEARER_TOKEN"


@dataclass(frozen=True)
class AuthConfig:
    """How to authenticate one outbound call. `params` is a non-secret bag interpreted
    per `auth_type` (e.g. API_KEY_HEADER reads `params["header_name"]`, defaulting to
    `X-API-Key`; BASIC reads `params["username"]`). The one secret (key/password/token
    itself) is never put in `params` — it is resolved separately via `SecretStore` and
    passed to `apply_auth` directly (SECURITY-12)."""

    auth_type: AuthType
    params: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class AppliedAuth:
    """What a strategy produces: headers/query params to merge into the outbound request."""

    headers: dict[str, str] = field(default_factory=dict)
    query_params: dict[str, str] = field(default_factory=dict)
