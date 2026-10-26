import pytest

from src.modules.integration.webhooks_outbound.application.service import WebhookEndpointService
from src.modules.integration.webhooks_outbound.infrastructure.memory import (
    InMemoryWebhookEndpointRepository,
)
from src.shared.secrets import EnvSecretStore
from src.shared.types import TenantId, WebhookEndpointId


def _service() -> WebhookEndpointService:
    return WebhookEndpointService(InMemoryWebhookEndpointRepository(), EnvSecretStore())


def test_register_returns_endpoint_and_raw_secret_once() -> None:
    service = _service()
    endpoint, raw_secret = service.register(
        tenant_id=TenantId("tnt_demo"),
        name="Procurement system",
        url="https://example.com/hooks",
        event_types=None,
    )
    assert endpoint.tenant_id == TenantId("tnt_demo")
    assert endpoint.is_active is True
    assert raw_secret.startswith("whsec_")


def test_pause_and_resume_round_trip() -> None:
    service = _service()
    endpoint, _ = service.register(
        tenant_id=TenantId("tnt_demo"),
        name="Warehouse feed",
        url="https://example.com/wh",
        event_types=None,
    )
    paused = service.pause(endpoint.endpoint_id, tenant_id=TenantId("tnt_demo"))
    assert paused.is_active is False
    resumed = service.resume(endpoint.endpoint_id, tenant_id=TenantId("tnt_demo"))
    assert resumed.is_active is True


def test_pause_unknown_endpoint_raises() -> None:
    service = _service()
    try:
        service.pause(WebhookEndpointId("whep_nope"), tenant_id=TenantId("tnt_demo"))
        raise AssertionError("expected WebhookEndpointNotFound")
    except Exception as exc:
        assert "whep_nope" in str(exc)


def test_pause_wrong_tenant_raises_not_found() -> None:
    """A different tenant's endpoint ID must read as not-found, not as a permission
    error that would confirm the ID exists — fail-closed against IDOR."""
    service = _service()
    endpoint, _ = service.register(
        tenant_id=TenantId("tnt_demo"),
        name="Warehouse feed",
        url="https://example.com/wh",
        event_types=None,
    )
    try:
        service.pause(endpoint.endpoint_id, tenant_id=TenantId("tnt_other"))
        raise AssertionError("expected WebhookEndpointNotFound")
    except Exception as exc:
        assert str(endpoint.endpoint_id) in str(exc)


@pytest.mark.parametrize("url", ["not-a-url", "ftp://reseller.example.com/hook", "https://"])
def test_register_rejects_a_url_that_is_not_http_and_stores_nothing(url: str) -> None:
    svc = _service()
    with pytest.raises(ValueError, match="url"):
        svc.register(tenant_id=TenantId("tnt_demo"), name="Orders", url=url, event_types=None)
    assert svc._repository.list_by_tenant(TenantId("tnt_demo")) == []  # type: ignore[attr-defined]


def test_register_rejects_a_blank_name() -> None:
    svc = _service()
    with pytest.raises(ValueError, match="name"):
        svc.register(
            tenant_id=TenantId("tnt_demo"),
            name="  ",
            url="https://reseller.example.com/hook",
            event_types=None,
        )


def test_register_with_auth_stores_the_auth_secret_apart_from_the_signing_secret() -> None:
    from src.shared.erp_auth import AuthType

    secrets = EnvSecretStore()
    svc = WebhookEndpointService(InMemoryWebhookEndpointRepository(), secrets)
    endpoint, signing_secret = svc.register(
        tenant_id=TenantId("tnt_demo"),
        name="Orders",
        url="https://reseller.example.com/hook",
        event_types=None,
        auth_type=AuthType.API_KEY_HEADER,
        auth_params={"header_name": "X-Partner-Key"},
        auth_secret="partner-key-123",
    )
    assert endpoint.auth_type is AuthType.API_KEY_HEADER
    assert endpoint.auth_params == {"header_name": "X-Partner-Key"}
    assert endpoint.auth_secret_ref is not None
    assert secrets.get_secret(endpoint.auth_secret_ref) == "partner-key-123"
    assert secrets.get_secret(endpoint.secret_ref) == signing_secret
    assert signing_secret != "partner-key-123"


def test_register_without_auth_has_no_auth_secret() -> None:
    from src.shared.erp_auth import AuthType

    svc = _service()
    endpoint, _ = svc.register(
        tenant_id=TenantId("tnt_demo"),
        name="Orders",
        url="https://reseller.example.com/hook",
        event_types=None,
    )
    assert endpoint.auth_type is AuthType.NONE
    assert endpoint.auth_secret_ref is None


@pytest.mark.parametrize(
    ("auth_type", "params", "secret", "message"),
    [
        ("API_KEY_HEADER", {}, None, "needs a secret"),
        ("BEARER_TOKEN", {}, "", "needs a secret"),
        ("BASIC", {}, "pw", "username"),
    ],
)
def test_register_rejects_incomplete_auth_and_stores_nothing(
    auth_type: str, params: dict[str, str], secret: str | None, message: str
) -> None:
    from src.shared.erp_auth import AuthType

    repo = InMemoryWebhookEndpointRepository()
    svc = WebhookEndpointService(repo, EnvSecretStore())
    with pytest.raises(ValueError, match=message):
        svc.register(
            tenant_id=TenantId("tnt_demo"),
            name="Orders",
            url="https://reseller.example.com/hook",
            event_types=None,
            auth_type=AuthType(auth_type),
            auth_params=params,
            auth_secret=secret,
        )
    assert repo.list_by_tenant(TenantId("tnt_demo")) == []
