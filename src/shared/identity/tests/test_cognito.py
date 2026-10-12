"""Unit tests for `CognitoIdentityProvider`'s verification logic — fast, no network.

A locally-generated RSA keypair stands in for Cognito's; a fake `jwk_client` (the same
injection point production code uses to swap floci/AWS) returns its public key instead
of fetching one over HTTP. This exercises every rejection path deterministically; the
live round-trip against a real (floci) Cognito user pool is
`tests/integration/test_cognito_identity.py`.
"""

from __future__ import annotations

import time

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from src.shared.identity.cognito import CognitoIdentityProvider

pytest.importorskip("cryptography")

_ISSUER = "https://cognito-idp.us-east-1.amazonaws.com/us-east-1_test"
_CLIENT_ID = "test-client-id"
_PRIVATE_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


class _FakeSigningKey:
    def __init__(self, key: object) -> None:
        self.key = key


class _FakeJwkClient:
    """Stands in for `PyJWKClient`: same `get_signing_key_from_jwt` shape, no HTTP."""

    def get_signing_key_from_jwt(self, token: str) -> _FakeSigningKey:
        return _FakeSigningKey(_PRIVATE_KEY.public_key())


def _provider() -> CognitoIdentityProvider:
    return CognitoIdentityProvider(
        user_pool_id="us-east-1_test",
        client_id=_CLIENT_ID,
        issuer=_ISSUER,
        jwk_client=_FakeJwkClient(),
    )


def _token(**overrides: object) -> str:
    claims = {
        "iss": _ISSUER,
        "aud": _CLIENT_ID,
        "token_use": "id",
        "exp": int(time.time()) + 3600,
        "sub": "user-123",
        "custom:tenant_id": "tnt_demo",
        "cognito:groups": ["OPERATOR"],
    }
    claims.update(overrides)
    return jwt.encode(claims, _PRIVATE_KEY, algorithm="RS256")


def _access_token(**overrides: object) -> str:
    """A client_credentials-shaped token: `client_id` not `aud`, tenant/roles come from
    `scope`, not custom attributes/groups — see the module docstring on `cognito.py`."""
    claims = {
        "iss": _ISSUER,
        "token_use": "access",
        "exp": int(time.time()) + 3600,
        "client_id": _CLIENT_ID,
        "scope": "o2c/tenant.tnt_demo o2c/role.RESELLER",
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
    assert _provider().authenticate(_headers(_token(iss="https://evil.example/pool"))) is None


def test_wrong_audience_is_rejected() -> None:
    assert _provider().authenticate(_headers(_token(aud="some-other-client"))) is None


def test_expired_token_is_rejected() -> None:
    assert _provider().authenticate(_headers(_token(exp=int(time.time()) - 60))) is None


def test_access_token_is_rejected_not_just_id_token() -> None:
    """`custom:tenant_id`/`cognito:groups` live on the ID token; an access token
    presented here must not be silently trusted just because it's well-signed."""
    assert _provider().authenticate(_headers(_token(token_use="access"))) is None


def test_missing_tenant_claim_is_rejected() -> None:
    token = _token()
    claims = jwt.decode(token, options={"verify_signature": False})
    del claims["custom:tenant_id"]
    retoken = jwt.encode(claims, _PRIVATE_KEY, algorithm="RS256")
    assert _provider().authenticate(_headers(retoken)) is None


def test_tampered_signature_is_rejected() -> None:
    token = _token()
    tampered = token[:-4] + ("aaaa" if not token.endswith("aaaa") else "bbbb")
    assert _provider().authenticate(_headers(tampered)) is None


def test_missing_groups_claim_means_no_roles_not_a_rejection() -> None:
    """A valid user with no group memberships is a real, legitimate case (not yet
    assigned a role) — authenticate, just with an empty roles tuple."""
    token = _token(**{"cognito:groups": []})
    principal = _provider().authenticate(_headers(token))
    assert principal is not None
    assert principal.roles == ()


# --- client_credentials (machine-to-machine, access tokens — no user involved) ---


def test_valid_access_token_derives_tenant_and_roles_from_scope() -> None:
    principal = _provider().authenticate(_headers(_access_token()))
    assert principal is not None
    assert principal.tenant_id == "tnt_demo"
    assert principal.roles == ("RESELLER",)


def test_access_token_ignores_aud_and_checks_client_id_instead() -> None:
    """Cognito access tokens genuinely have no `aud` claim — confirms the provider
    doesn't accidentally require one for this token type (it would for an ID token)."""
    token = _access_token()
    assert "aud" not in jwt.decode(token, options={"verify_signature": False})
    assert _provider().authenticate(_headers(token)) is not None


def test_access_token_wrong_client_id_is_rejected() -> None:
    token = _access_token(client_id="someone-elses-client")
    assert _provider().authenticate(_headers(token)) is None


def test_access_token_with_no_tenant_scope_is_rejected() -> None:
    token = _access_token(scope="o2c/role.RESELLER")  # no tenant.* scope at all
    assert _provider().authenticate(_headers(token)) is None


def test_access_token_with_two_tenant_scopes_is_rejected_not_guessed() -> None:
    """Ambiguous — which tenant does this client act as? Reject rather than pick one."""
    token = _access_token(scope="o2c/tenant.tnt_demo o2c/tenant.tnt_other")
    assert _provider().authenticate(_headers(token)) is None


def test_access_token_scope_from_a_different_resource_server_is_ignored() -> None:
    """A scope that merely *contains* the word "tenant" from an unrelated resource
    server must not be mistaken for this API's tenant scope."""
    token = _access_token(scope="some-other-api/tenant.tnt_demo")
    assert _provider().authenticate(_headers(token)) is None


def test_access_token_with_multiple_role_scopes_captures_all_of_them() -> None:
    token = _access_token(scope="o2c/tenant.tnt_demo o2c/role.RESELLER o2c/role.BILLING")
    principal = _provider().authenticate(_headers(token))
    assert principal is not None
    assert principal.roles == ("RESELLER", "BILLING")


def test_access_token_with_no_role_scopes_means_no_roles_not_a_rejection() -> None:
    token = _access_token(scope="o2c/tenant.tnt_demo")
    principal = _provider().authenticate(_headers(token))
    assert principal is not None
    assert principal.roles == ()
