from __future__ import annotations

from src.shared.identity.provider import HeaderStubIdentityProvider


def test_stub_trusts_headers_outright() -> None:
    principal = HeaderStubIdentityProvider().authenticate(
        {"x-tenant-id": "tnt_1", "x-roles": "OPERATOR,ADMIN"}
    )
    assert principal is not None
    assert principal.tenant_id == "tnt_1"
    assert principal.roles == ("OPERATOR", "ADMIN")


def test_stub_defaults_tenant_when_header_absent() -> None:
    """Deliberately permissive — local dev convenience, not a security boundary
    (KeycloakIdentityProvider is the one that actually rejects)."""
    principal = HeaderStubIdentityProvider().authenticate({})
    assert principal is not None
    assert principal.tenant_id == "tnt_demo"
    assert principal.roles == ()
