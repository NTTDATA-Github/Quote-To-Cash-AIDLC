"""Declarative outbound-auth strategies, shared by anything that dials an operator-
supplied ERP URL on the app's behalf (today: onboarding probes; later: real connections
too, once a probed source is promoted). See `strategies.py` for what's deliberately NOT
here (OAuth1 signing, OAuth2 authorization-code) and why.
"""

from __future__ import annotations

from .strategies import AUTH_STRATEGIES, AuthStrategy, apply_auth
from .types import AppliedAuth, AuthConfig, AuthType

__all__ = [
    "AUTH_STRATEGIES",
    "AppliedAuth",
    "AuthConfig",
    "AuthStrategy",
    "AuthType",
    "apply_auth",
]
