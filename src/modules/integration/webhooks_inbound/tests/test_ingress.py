from __future__ import annotations

from src.modules.integration.erp.domain.status_mapping import CanonicalStatus
from src.modules.integration.webhooks_inbound.application.ingress import (
    InboundWebhook,
    InboundWebhookService,
    IngressOutcome,
    WebhookAuthMode,
)
from src.modules.integration.webhooks_inbound.domain.signature import compute_signature
from src.modules.integration.webhooks_inbound.infrastructure.memory import (
    InMemoryDedupStore,
    InMemoryEventInbox,
    InMemoryOrderLocator,
)
from src.shared.types import ConnectionId, OrderId

_SECRET = "whsec_test"
_CONN = ConnectionId("conn_1")
_BODY = b'{"erp_order_id":"S001","state":"sale"}'


class FakeSecrets:
    def secret_for(self, connection_id: ConnectionId) -> str | None:
        return _SECRET if connection_id == _CONN else None


class RecordingStatus:
    def __init__(self) -> None:
        self.applied: list[tuple[str, CanonicalStatus]] = []

    def apply_status(self, order_id: OrderId, status: CanonicalStatus) -> None:
        self.applied.append((order_id, status))


def _service(
    locator: InMemoryOrderLocator,
    status: RecordingStatus,
    inbox: InMemoryEventInbox | None = None,
) -> InboundWebhookService:
    return InboundWebhookService(
        secrets=FakeSecrets(),
        dedup=InMemoryDedupStore(),
        inbox=inbox if inbox is not None else InMemoryEventInbox(),
        locator=locator,
        order_status=status,
    )


def _webhook(
    native_status: str = "sale", event_ref: str = "evt_1", signature: str | None = None
) -> InboundWebhook:
    return InboundWebhook(
        connection_id=_CONN,
        erp_type="ODOO",
        erp_order_id="S001",
        native_fields={"state": native_status},
        event_ref=event_ref,
        raw_body=_BODY,
        signature=signature if signature is not None else compute_signature(_SECRET, _BODY),
    )


def test_refresh_pulls_shipments_once_the_order_is_known() -> None:
    locator = InMemoryOrderLocator()
    locator.record(_CONN, "S001", OrderId("ord_1"))
    seen: list[tuple[str, str, str]] = []

    def refresh(connection_id: ConnectionId, erp_order_id: str, order_id: str) -> None:
        seen.append((str(connection_id), erp_order_id, order_id))

    service = InboundWebhookService(
        secrets=FakeSecrets(),
        dedup=InMemoryDedupStore(),
        inbox=InMemoryEventInbox(),
        locator=locator,
        order_status=RecordingStatus(),
        refresh=refresh,
    )
    assert service.handle(_webhook()) is IngressOutcome.ACCEPTED
    assert seen == [("conn_1", "S001", "ord_1")]


def test_accepted_applies_status() -> None:
    locator = InMemoryOrderLocator()
    locator.record(_CONN, "S001", OrderId("ord_1"))
    status = RecordingStatus()
    outcome = _service(locator, status).handle(_webhook())
    assert outcome is IngressOutcome.ACCEPTED
    assert status.applied == [("ord_1", CanonicalStatus.CONFIRMED)]


def test_authenticated_body_is_stored_raw_before_it_is_understood() -> None:
    inbox = InMemoryEventInbox()
    weird = b"\xff\xfe not json at all"
    webhook = InboundWebhook(
        connection_id=_CONN,
        erp_type="ODOO",
        erp_order_id="",
        native_fields={},
        event_ref="evt_raw",
        raw_body=weird,
        signature=compute_signature(_SECRET, weird),
    )
    outcome = _service(InMemoryOrderLocator(), RecordingStatus(), inbox).handle(webhook)
    assert outcome is IngressOutcome.UNATTRIBUTABLE
    assert inbox.rows == [(str(_CONN), weird)]


def test_unauthorized_body_is_not_stored() -> None:
    inbox = InMemoryEventInbox()
    outcome = _service(InMemoryOrderLocator(), RecordingStatus(), inbox).handle(
        _webhook(signature="deadbeef")
    )
    assert outcome is IngressOutcome.UNAUTHORIZED
    assert inbox.rows == []


def test_bad_signature_is_unauthorized() -> None:
    locator = InMemoryOrderLocator()
    locator.record(_CONN, "S001", OrderId("ord_1"))
    outcome = _service(locator, RecordingStatus()).handle(_webhook(signature="deadbeef"))
    assert outcome is IngressOutcome.UNAUTHORIZED


def test_unattributable_is_ignored() -> None:
    outcome = _service(InMemoryOrderLocator(), RecordingStatus()).handle(_webhook())
    assert outcome is IngressOutcome.UNATTRIBUTABLE


def test_duplicate_delivery_is_detected() -> None:
    locator = InMemoryOrderLocator()
    locator.record(_CONN, "S001", OrderId("ord_1"))
    svc = _service(locator, RecordingStatus())
    assert svc.handle(_webhook(event_ref="evt_9")) is IngressOutcome.ACCEPTED
    assert svc.handle(_webhook(event_ref="evt_9")) is IngressOutcome.DUPLICATE


def test_unmapped_status_is_no_transition() -> None:
    locator = InMemoryOrderLocator()
    locator.record(_CONN, "S001", OrderId("ord_1"))
    status = RecordingStatus()
    outcome = _service(locator, status).handle(_webhook(native_status="draft"))
    assert outcome is IngressOutcome.NO_TRANSITION
    assert status.applied == []


def test_shared_secret_mode_accepted_with_correct_secret() -> None:
    """Odoo path: the secret itself is `signature`, checked directly (no HMAC over body)."""
    locator = InMemoryOrderLocator()
    locator.record(_CONN, "S001", OrderId("ord_1"))
    status = RecordingStatus()
    webhook = InboundWebhook(
        connection_id=_CONN,
        erp_type="ODOO",
        erp_order_id="S001",
        native_fields={"state": "sale"},
        event_ref="evt_shared_1",
        raw_body=_BODY,
        signature=_SECRET,  # the raw secret, not a computed signature
        auth_mode=WebhookAuthMode.SHARED_SECRET,
    )
    outcome = _service(locator, status).handle(webhook)
    assert outcome is IngressOutcome.ACCEPTED
    assert status.applied == [("ord_1", CanonicalStatus.CONFIRMED)]


def test_shared_secret_mode_rejects_wrong_secret() -> None:
    locator = InMemoryOrderLocator()
    locator.record(_CONN, "S001", OrderId("ord_1"))
    webhook = InboundWebhook(
        connection_id=_CONN,
        erp_type="ODOO",
        erp_order_id="S001",
        native_fields={"state": "sale"},
        event_ref="evt_shared_2",
        raw_body=_BODY,
        signature="wrong-secret",
        auth_mode=WebhookAuthMode.SHARED_SECRET,
    )
    outcome = _service(locator, RecordingStatus()).handle(webhook)
    assert outcome is IngressOutcome.UNAUTHORIZED


def test_shared_secret_mode_does_not_accept_a_valid_hmac_signature() -> None:
    """A caller can't send an HMAC digest and get through shared-secret mode by luck —
    the two schemes check completely different things (digest-over-body vs. raw-secret)."""
    locator = InMemoryOrderLocator()
    locator.record(_CONN, "S001", OrderId("ord_1"))
    webhook = InboundWebhook(
        connection_id=_CONN,
        erp_type="ODOO",
        erp_order_id="S001",
        native_fields={"state": "sale"},
        event_ref="evt_shared_3",
        raw_body=_BODY,
        signature=compute_signature(_SECRET, _BODY),  # an HMAC digest, not the raw secret
        auth_mode=WebhookAuthMode.SHARED_SECRET,
    )
    outcome = _service(locator, RecordingStatus()).handle(webhook)
    assert outcome is IngressOutcome.UNAUTHORIZED
