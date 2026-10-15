from __future__ import annotations

import pytest
from src.shared.erp_auth import AuthConfig, AuthType, apply_auth


def test_none_auth_applies_nothing() -> None:
    applied = apply_auth(AuthConfig(auth_type=AuthType.NONE), secret=None)
    assert applied.headers == {}
    assert applied.query_params == {}


def test_api_key_header_uses_default_header_name() -> None:
    applied = apply_auth(AuthConfig(auth_type=AuthType.API_KEY_HEADER), secret="abc123")
    assert applied.headers == {"X-API-Key": "abc123"}


def test_api_key_header_respects_custom_header_name() -> None:
    config = AuthConfig(auth_type=AuthType.API_KEY_HEADER, params={"header_name": "X-Acme-Token"})
    applied = apply_auth(config, secret="abc123")
    assert applied.headers == {"X-Acme-Token": "abc123"}


def test_api_key_header_requires_a_secret() -> None:
    with pytest.raises(ValueError, match="requires a secret"):
        apply_auth(AuthConfig(auth_type=AuthType.API_KEY_HEADER), secret=None)


def test_basic_auth_encodes_username_and_password() -> None:
    config = AuthConfig(auth_type=AuthType.BASIC, params={"username": "admin"})
    applied = apply_auth(config, secret="s3cret")
    # base64("admin:s3cret")
    assert applied.headers == {"Authorization": "Basic YWRtaW46czNjcmV0"}


def test_bearer_token_sets_authorization_header() -> None:
    applied = apply_auth(AuthConfig(auth_type=AuthType.BEARER_TOKEN), secret="tok_abc")
    assert applied.headers == {"Authorization": "Bearer tok_abc"}


def test_bearer_token_requires_a_secret() -> None:
    with pytest.raises(ValueError, match="requires a secret"):
        apply_auth(AuthConfig(auth_type=AuthType.BEARER_TOKEN), secret="")
