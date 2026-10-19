"""Integration test for Phase 3 item B — `build_container(profile="postgres")`.

Proves the postgres-profile wiring is correct: real `OrderService` + `OrderProcessor` +
the item-A Postgres repos/projection store, all reached through the same composition
root as the memory profile. Self-skips like `test_postgres_adapters.py` when Postgres/
deps aren't reachable.

Scope: routing (`order_processor`) only, not delivery. `DeliveryHandler` resolves a
connection's secret via `SecretsManagerSecretStore` (boto3 -> Secrets Manager/floci),
which isn't up in this check — that needs floci and belongs to item I (full E2E
verification), not this composition-wiring check.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import pytest

pytest.importorskip("sqlalchemy")

from sqlalchemy import text  # noqa: E402
from src.composition import build_container  # noqa: E402
from src.modules.integration.erp.application.ports import ErpPartnerOrderLine  # noqa: E402
from src.modules.reference.connections.domain.models import ErpConnection  # noqa: E402
from src.modules.reference.tenancy.domain.models import (  # noqa: E402
    BindingStatus,
    TenantConnectionBinding,
)
from src.shared.persistence.engine import get_session_factory  # noqa: E402
from src.shared.persistence.event_store import PostgresEventStore  # noqa: E402
from src.shared.types import BindingId, ConnectionId, TenantId  # noqa: E402

if TYPE_CHECKING:
    from src.shared.config import Settings

try:
    _factory = get_session_factory()
    with _factory() as _probe:
        _probe.execute(text("SELECT 1"))
except Exception as exc:  # pragma: no cover - environment-dependent
    pytest.skip(f"Postgres not reachable: {exc}", allow_module_level=True)


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


def _postgres_settings() -> Settings:
    from dataclasses import replace

    from src.shared.config import get_settings

    # Env-loaded settings (DATABASE_URL etc.) with only the profile overridden.
    return replace(get_settings(), profile="postgres", erp_adapter_mode="stub")


def test_postgres_profile_places_and_routes_an_order() -> None:
    container = build_container(_postgres_settings())
    assert container.bus is None  # postgres profile: no synchronous in-memory bus
    container.drain()  # no-op; must not raise

    tenant = TenantId(_id("tnt"))
    connection = ConnectionId(_id("conn"))
    container.connections.add(
        ErpConnection(
            connection_id=connection,
            erp_type="ODOO",
            instance_label="Test Odoo",
            base_url="http://odoo:8069",
            credentials={"database": "odoo", "username": "admin"},
            secret_ref="env:ODOO_SECRET_UNUSED",
        )
    )
    sku = _id("ANVIL")
    container.bindings.add(
        TenantConnectionBinding(
            binding_id=BindingId(_id("bind")),
            tenant_id=tenant,
            connection_id=connection,
            erp_customer_id="CUST-1",
            status=BindingStatus.VERIFIED,
        )
    )

    order_id = container.order_service.observe_erp_order(
        tenant_id=tenant,
        connection_id=str(connection),
        erp_order_id="S00042",
        client_reference="S00042",
        lines=[ErpPartnerOrderLine(product_key=sku, quantity="2", unit_price="19.99")],
        subsidiary_id="sub_demo",
    )
    try:
        event_store = PostgresEventStore(_factory)
        observed = event_store.load(order_id)
        assert [e.event_type for e in observed] == ["OrderObserved"]
        for event in observed:
            container.order_projector.handle(event)

        operator = container.projections.get_operator_view(order_id)
        assert operator is not None
        assert operator.status == "SENT_TO_ERP"
        assert operator.erp_order_id == "S00042"
        assert operator.owning_connection_id == str(connection)
    finally:
        # This order/connection has no consumer of its own; leaving rows behind would
        # make item C's worker (which iterates ALL active connections, and the relay
        # picks up ALL unpublished outbox rows) trip over test data on its next run —
        # a stray connection with a fake secret_ref crashes every reconcile/delivery
        # attempt. Learned this the hard way; see aidlc-docs/audit.md.
        with _factory() as session, session.begin():
            session.execute(text("DELETE FROM outbox WHERE stream_id = :oid"), {"oid": order_id})
            session.execute(text("DELETE FROM events WHERE stream_id = :oid"), {"oid": order_id})
            session.execute(
                text("DELETE FROM order_status_history WHERE order_id = :oid"), {"oid": order_id}
            )
            session.execute(text("DELETE FROM orders WHERE order_id = :oid"), {"oid": order_id})
            session.execute(
                text("DELETE FROM tenant_connection_bindings WHERE connection_id = :cid"),
                {"cid": str(connection)},
            )
            session.execute(
                text("DELETE FROM erp_connections WHERE connection_id = :cid"),
                {"cid": str(connection)},
            )


def test_postgres_profile_observes_the_same_erp_order_once() -> None:
    container = build_container(_postgres_settings())
    tenant = TenantId(_id("tnt"))
    line = ErpPartnerOrderLine(product_key="ANVIL", quantity="1", unit_price="19.99")
    order_id = container.order_service.observe_erp_order(
        tenant_id=tenant,
        connection_id="conn_1",
        erp_order_id="S00042",
        client_reference="S00042",
        lines=[line],
        subsidiary_id="sub_demo",
    )
    try:
        again = container.order_service.observe_erp_order(
            tenant_id=tenant,
            connection_id="conn_1",
            erp_order_id="S00042",
            client_reference="S00042",
            lines=[line],
            subsidiary_id="sub_demo",
        )
        assert again == order_id
        event_store = PostgresEventStore(_factory)
        assert [event.event_type for event in event_store.load(order_id)] == ["OrderObserved"]
    finally:
        with _factory() as session, session.begin():
            session.execute(text("DELETE FROM outbox WHERE stream_id = :oid"), {"oid": order_id})
            session.execute(text("DELETE FROM events WHERE stream_id = :oid"), {"oid": order_id})
            session.execute(
                text("DELETE FROM order_status_history WHERE order_id = :oid"), {"oid": order_id}
            )
            session.execute(text("DELETE FROM orders WHERE order_id = :oid"), {"oid": order_id})
