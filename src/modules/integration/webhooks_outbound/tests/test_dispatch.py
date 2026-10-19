import json
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from src.modules.integration.webhooks_outbound.application.dispatch import (
    MAX_ATTEMPTS,
    WebhookDeliveryRetry,
    WebhookDispatchService,
)
from src.modules.integration.webhooks_outbound.application.ports import WebhookSendResult
from src.modules.integration.webhooks_outbound.domain.models import DeliveryStatus, WebhookEndpoint
from src.modules.integration.webhooks_outbound.infrastructure.memory import (
    InMemoryWebhookDeliveryRepository,
    InMemoryWebhookEndpointRepository,
)
from src.shared.eventsourcing import StoredEvent
from src.shared.secrets import EnvSecretStore
from src.shared.types import TenantId, WebhookEndpointId, generate_id


class _FakeSender:
    def __init__(self, success: bool) -> None:
        self.success = success
        self.calls: list[tuple[str, dict, bytes]] = []

    def send(self, url, headers, body):
        self.calls.append((url, headers, body))
        return WebhookSendResult(
            success=self.success,
            status_code=200 if self.success else 503,
            error=None if self.success else "boom",
        )


class _FakeOrders:
    def get_operator_view(self, order_id: str):
        return SimpleNamespace(client_reference="PO-88213", status="SENT_TO_ERP")


def _event(event_type: str = "OrderSentToErp", tenant_id: str = "tnt_demo") -> StoredEvent:
    return StoredEvent(
        stream_id="ord_1",
        aggregate_type="Order",
        version=4,
        event_type=event_type,
        event_id=generate_id("evt"),
        occurred_at=datetime.now(UTC),
        payload={"order_id": "ord_1"},
        tenant_id=tenant_id,
    )


def _register_endpoint(
    endpoints: InMemoryWebhookEndpointRepository, secrets: EnvSecretStore, **overrides
) -> WebhookEndpoint:
    endpoint = WebhookEndpoint(
        endpoint_id=WebhookEndpointId(generate_id("whep")),
        tenant_id=TenantId("tnt_demo"),
        name="Procurement system",
        url="https://example.com/hooks",
        secret_ref="webhook-endpoint/test",
        event_types=None,
        is_active=True,
    )
    for key, value in overrides.items():
        setattr(endpoint, key, value)
    endpoints.add(endpoint)
    secrets.put_secret(endpoint.secret_ref, "whsec_test")
    return endpoint


def test_no_endpoints_is_a_noop() -> None:
    service = WebhookDispatchService(
        endpoints=InMemoryWebhookEndpointRepository(),
        deliveries=InMemoryWebhookDeliveryRepository(),
        secrets=EnvSecretStore(),
        sender=_FakeSender(success=True),
        orders=_FakeOrders(),
    )
    service.handle(_event())  # must not raise


def test_ignores_non_dispatchable_event_types() -> None:
    endpoints = InMemoryWebhookEndpointRepository()
    secrets = EnvSecretStore()
    _register_endpoint(endpoints, secrets)
    sender = _FakeSender(success=True)
    service = WebhookDispatchService(
        endpoints=endpoints,
        deliveries=InMemoryWebhookDeliveryRepository(),
        secrets=secrets,
        sender=sender,
        orders=_FakeOrders(),
    )
    service.handle(_event(event_type="OrderSubmitted"))
    assert sender.calls == []


def test_successful_delivery_signs_and_records_delivered() -> None:
    endpoints = InMemoryWebhookEndpointRepository()
    secrets = EnvSecretStore()
    endpoint = _register_endpoint(endpoints, secrets)
    deliveries = InMemoryWebhookDeliveryRepository()
    sender = _FakeSender(success=True)
    service = WebhookDispatchService(
        endpoints=endpoints,
        deliveries=deliveries,
        secrets=secrets,
        sender=sender,
        orders=_FakeOrders(),
    )

    event = _event()
    service.handle(event)  # must not raise

    assert len(sender.calls) == 1
    url, headers, body = sender.calls[0]
    assert url == endpoint.url
    assert headers["X-Signature"].startswith("t=") and ",v1=" in headers["X-Signature"]
    parsed = json.loads(body)
    assert parsed["event"] == "OrderSentToErp"
    assert parsed["order"] == {"id": "ord_1", "number": "PO-88213", "status": "SENT_TO_ERP"}

    recorded = deliveries.find(endpoint.endpoint_id, event.event_id)
    assert recorded is not None
    assert recorded.status is DeliveryStatus.DELIVERED
    assert recorded.attempts == 1


def test_order_cancelled_is_dispatched() -> None:
    """Previously a documented gap — a cancellation never reached a reseller's webhook."""
    endpoints = InMemoryWebhookEndpointRepository()
    secrets = EnvSecretStore()
    _register_endpoint(endpoints, secrets)
    sender = _FakeSender(success=True)
    service = WebhookDispatchService(
        endpoints=endpoints,
        deliveries=InMemoryWebhookDeliveryRepository(),
        secrets=secrets,
        sender=sender,
        orders=_FakeOrders(),
    )
    service.handle(_event(event_type="OrderCancelled"))
    assert len(sender.calls) == 1
    assert json.loads(sender.calls[0][2])["event"] == "OrderCancelled"


def test_endpoint_not_subscribed_to_event_type_is_skipped() -> None:
    endpoints = InMemoryWebhookEndpointRepository()
    secrets = EnvSecretStore()
    _register_endpoint(endpoints, secrets, event_types=frozenset({"OrderConfirmed"}))
    sender = _FakeSender(success=True)
    service = WebhookDispatchService(
        endpoints=endpoints,
        deliveries=InMemoryWebhookDeliveryRepository(),
        secrets=secrets,
        sender=sender,
        orders=_FakeOrders(),
    )
    service.handle(_event(event_type="OrderSentToErp"))
    assert sender.calls == []


def test_paused_endpoint_is_skipped() -> None:
    endpoints = InMemoryWebhookEndpointRepository()
    secrets = EnvSecretStore()
    _register_endpoint(endpoints, secrets, is_active=False)
    sender = _FakeSender(success=True)
    service = WebhookDispatchService(
        endpoints=endpoints,
        deliveries=InMemoryWebhookDeliveryRepository(),
        secrets=secrets,
        sender=sender,
        orders=_FakeOrders(),
    )
    service.handle(_event())
    assert sender.calls == []


def test_transient_failure_raises_for_redrive_and_stays_retrying() -> None:
    endpoints = InMemoryWebhookEndpointRepository()
    secrets = EnvSecretStore()
    endpoint = _register_endpoint(endpoints, secrets)
    deliveries = InMemoryWebhookDeliveryRepository()
    sender = _FakeSender(success=False)
    service = WebhookDispatchService(
        endpoints=endpoints,
        deliveries=deliveries,
        secrets=secrets,
        sender=sender,
        orders=_FakeOrders(),
    )

    event = _event()
    with pytest.raises(WebhookDeliveryRetry):
        service.handle(event)

    recorded = deliveries.find(endpoint.endpoint_id, event.event_id)
    assert recorded is not None
    assert recorded.status is DeliveryStatus.RETRYING
    assert recorded.attempts == 1


def test_exhausted_retries_marks_failed_and_stops_raising() -> None:
    """Simulates Service Bus redelivering the same message MAX_ATTEMPTS times."""
    endpoints = InMemoryWebhookEndpointRepository()
    secrets = EnvSecretStore()
    endpoint = _register_endpoint(endpoints, secrets)
    deliveries = InMemoryWebhookDeliveryRepository()
    sender = _FakeSender(success=False)
    service = WebhookDispatchService(
        endpoints=endpoints,
        deliveries=deliveries,
        secrets=secrets,
        sender=sender,
        orders=_FakeOrders(),
    )

    event = _event()
    for _ in range(MAX_ATTEMPTS - 1):
        with pytest.raises(WebhookDeliveryRetry):
            service.handle(event)

    service.handle(event)  # the MAX_ATTEMPTS-th attempt: FAILED, must not raise

    recorded = deliveries.find(endpoint.endpoint_id, event.event_id)
    assert recorded is not None
    assert recorded.status is DeliveryStatus.FAILED
    assert recorded.attempts == MAX_ATTEMPTS
