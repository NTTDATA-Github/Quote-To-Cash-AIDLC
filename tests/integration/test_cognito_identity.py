"""Live integration test for `CognitoIdentityProvider` against floci's Cognito emulation
(real user pool, real user, real RS256-signed ID token, real JWKS fetch over HTTP).

Self-skips like the other integration tests when `AWS_ENDPOINT_URL` isn't set (never
falls back to real AWS — same guard as `test_odoo_webhook_shared_secret.py`) or floci's
cognito-idp isn't reachable.

**Known gap, not glossed over**: floci does not implement Cognito's OAuth2
`/oauth2/token` endpoint (confirmed by calling it directly — the request gets routed to
floci's S3 handler, never reaches its Cognito service, per floci's own logs). That
endpoint is the *only* way to obtain a real `client_credentials` (machine-to-machine)
token — `admin_initiate_auth` only covers user-based flows. So the `client_credentials`
issuance step itself cannot be verified live in this environment; only the ID-token path
gets that. What CAN be verified live below is the *access-token verification mechanics*
(JWKS lookup + RS256 signature + issuer, which are identical for every access token
regardless of how it was issued) using a real floci-issued access token from a normal
user login — it won't carry the custom `tenant.*`/`role.*` scopes a real M2M token would,
so it's expected to be correctly rejected for "no tenant scope", not for a signature or
JWKS failure. The scope-parsing logic itself is covered by the pure unit tests in
`src/shared/identity/tests/test_cognito.py`, which can fabricate whatever scopes it needs.
"""

from __future__ import annotations

import os
import uuid

import pytest

pytest.importorskip("boto3")

_AWS_ENDPOINT_URL = os.environ.get("AWS_ENDPOINT_URL")
if not _AWS_ENDPOINT_URL:
    pytest.skip(
        "AWS_ENDPOINT_URL not set (must point at floci, not real AWS)", allow_module_level=True
    )

import boto3  # noqa: E402
from src.shared.identity.cognito import CognitoIdentityProvider, issuer_url  # noqa: E402

try:
    _cognito = boto3.client("cognito-idp", endpoint_url=_AWS_ENDPOINT_URL, region_name="us-east-1")
    _cognito.list_user_pools(MaxResults=1)
except Exception as exc:  # pragma: no cover - environment-dependent
    pytest.skip(f"floci cognito-idp not reachable: {exc}", allow_module_level=True)


@pytest.fixture(scope="module")
def pool_and_token() -> tuple[str, str, str, str]:
    pool = _cognito.create_user_pool(
        PoolName=f"o2c-test-{uuid.uuid4().hex[:8]}",
        Schema=[{"Name": "tenant_id", "AttributeDataType": "String", "Mutable": True}],
    )
    pool_id = pool["UserPool"]["Id"]
    client = _cognito.create_user_pool_client(
        UserPoolId=pool_id,
        ClientName="o2c-test-client",
        ExplicitAuthFlows=["ALLOW_ADMIN_USER_PASSWORD_AUTH", "ALLOW_REFRESH_TOKEN_AUTH"],
    )
    client_id = client["UserPoolClient"]["ClientId"]

    username = f"testuser-{uuid.uuid4().hex[:8]}"
    _cognito.admin_create_user(
        UserPoolId=pool_id,
        Username=username,
        UserAttributes=[{"Name": "custom:tenant_id", "Value": "tnt_demo"}],
        MessageAction="SUPPRESS",
        TemporaryPassword="TempPass123!",
    )
    _cognito.admin_set_user_password(
        UserPoolId=pool_id, Username=username, Password="RealPass123!", Permanent=True
    )
    _cognito.create_group(GroupName="OPERATOR", UserPoolId=pool_id)
    _cognito.admin_add_user_to_group(UserPoolId=pool_id, Username=username, GroupName="OPERATOR")

    auth = _cognito.admin_initiate_auth(
        UserPoolId=pool_id,
        ClientId=client_id,
        AuthFlow="ADMIN_USER_PASSWORD_AUTH",
        AuthParameters={"USERNAME": username, "PASSWORD": "RealPass123!"},
    )
    id_token = auth["AuthenticationResult"]["IdToken"]
    access_token = auth["AuthenticationResult"]["AccessToken"]

    yield pool_id, client_id, id_token, access_token

    _cognito.delete_user_pool(UserPoolId=pool_id)


def _provider(pool_id: str, client_id: str) -> CognitoIdentityProvider:
    issuer = issuer_url(
        aws_endpoint_url=_AWS_ENDPOINT_URL, aws_region="us-east-1", user_pool_id=pool_id
    )
    return CognitoIdentityProvider(user_pool_id=pool_id, client_id=client_id, issuer=issuer)


def test_real_cognito_id_token_is_verified_end_to_end(
    pool_and_token: tuple[str, str, str, str],
) -> None:
    pool_id, client_id, id_token, _access_token = pool_and_token
    principal = _provider(pool_id, client_id).authenticate({"authorization": f"Bearer {id_token}"})
    assert principal is not None
    assert principal.tenant_id == "tnt_demo"
    assert principal.roles == ("OPERATOR",)


def test_token_from_a_different_client_id_is_rejected(
    pool_and_token: tuple[str, str, str, str],
) -> None:
    pool_id, _client_id, id_token, _access_token = pool_and_token
    wrong_provider = _provider(pool_id, "not-the-real-client-id")
    assert wrong_provider.authenticate({"authorization": f"Bearer {id_token}"}) is None


def test_real_access_token_signature_and_issuer_verify_correctly(
    pool_and_token: tuple[str, str, str, str], caplog: pytest.LogCaptureFixture
) -> None:
    """Exercises the access-token branch's crypto (real JWKS fetch + RS256 signature +
    issuer) against a real floci-issued token — see the module docstring for why this
    can't be a full client_credentials round trip in this environment. A user-login
    access token has no custom tenant/role scopes, so it must still be rejected — but
    the log message proves it got all the way to the scope check (i.e. past JWKS fetch +
    signature + issuer verification) rather than failing for some unrelated reason."""
    pool_id, client_id, _id_token, access_token = pool_and_token
    with caplog.at_level("INFO"):
        principal = _provider(pool_id, client_id).authenticate(
            {"authorization": f"Bearer {access_token}"}
        )
    assert principal is None
    assert "expected exactly one tenant scope" in caplog.text
