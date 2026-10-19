"""Unit tests for `KeycloakIdentityProvider`'s verification logic — fast, no network.

A locally-generated RSA keypair stands
in for Keycloak's, and a fake `jwk_client` returns its public key instead of fetching one
over HTTP.
"""

from __future__ import annotations

import time

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from src.shared.identity.keycloak import KeycloakIdentityProvider

pytest.importorskip("cryptography")

_ISSUER = "https://o2c-staging-keycloak.example.azurecontainerapps.io/realms/o2c"
_CLIENT_ID = "o2c-portal"
_PRIVATE_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


class _FakeSigningKey:
    def __init__(self, key: object) -> None:
        self.key = key


class _FakeJwkClient:
    def get_signing_key_from_jwt(self, token: str) -> _FakeSigningKey:
        return _FakeSigningKey(_PRIVATE_KEY.public_key())


def _provider() -> KeycloakIdentityProvider:
    return KeycloakIdentityProvider(
        issuer=_ISSUER,
        client_id=_CLIENT_ID,
        jwk_client=_FakeJwkClient(),
    )


def _token(**overrides: object) -> str:
    claims = {
        "iss": _ISSUER,
        "azp": _CLIENT_ID,
        "exp": int(time.time()) + 3600,
        "sub": "user-123",
        "tenant_id": "tnt_demo",
        "roles": ["OPERATOR"],
    }
    claims.update(overrides)
    return jwt.encode(claims, _PRIVATE_KEY, algorithm="RS256")


def _headers(token: str) -> dict[str, str]:
    return {"authorization": f"Bearer {token}"}


def test_valid_token_is_accepted() -> None:
    principal = _provider().authenticate(_headers(_token()))
    assert principal is not None
    assert principal.tenant_id == "tnt_demo"
    assert principal.roles == ("OPERATOR",)


def test_missing_authorization_header_is_rejected() -> None:
    assert _provider().authenticate({}) is None


def test_non_bearer_header_is_rejected() -> None:
    assert _provider().authenticate({"authorization": "Basic deadbeef"}) is None


def test_wrong_issuer_is_rejected() -> None:
    assert _provider().authenticate(_headers(_token(iss="https://evil.example/realms/o2c"))) is None


def test_wrong_azp_is_rejected() -> None:
    assert _provider().authenticate(_headers(_token(azp="some-other-client"))) is None


def test_expired_token_is_rejected() -> None:
    assert _provider().authenticate(_headers(_token(exp=int(time.time()) - 60))) is None


def test_missing_tenant_claim_is_rejected() -> None:
    token = _token()
    claims = jwt.decode(token, options={"verify_signature": False})
    del claims["tenant_id"]
    retoken = jwt.encode(claims, _PRIVATE_KEY, algorithm="RS256")
    assert _provider().authenticate(_headers(retoken)) is None


def test_tampered_signature_is_rejected() -> None:
    token = _token()
    tampered = token[:-4] + ("aaaa" if not token.endswith("aaaa") else "bbbb")
    assert _provider().authenticate(_headers(tampered)) is None


def test_missing_roles_claim_means_no_roles_not_a_rejection() -> None:
    token = _token(roles=[])
    principal = _provider().authenticate(_headers(token))
    assert principal is not None
    assert principal.roles == ()
