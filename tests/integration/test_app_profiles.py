"""Smoke test for Phase 3 item B — the actual FastAPI app (not just `build_container`
directly) under both profiles, via `TestClient`. Catches what a container-only test
can't: resolvers that reach into `container.bus` directly instead of `container.drain()`.

Self-skips like the other integration tests when Postgres/deps aren't reachable.
"""

from __future__ import annotations

import os
import uuid

import pytest

pytest.importorskip("sqlalchemy")
pytest.importorskip("httpx")

from sqlalchemy import text  # noqa: E402
from src.shared.config import get_settings  # noqa: E402
from src.shared.persistence.engine import get_session_factory  # noqa: E402

try:
    _factory = get_session_factory()
    with _factory() as _probe:
        _probe.execute(text("SELECT 1"))
except Exception as exc:  # pragma: no cover - environment-dependent
    pytest.skip(f"Postgres not reachable: {exc}", allow_module_level=True)


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


def _app(profile: str):
    os.environ["APP_PROFILE"] = profile
    os.environ["ERP_ADAPTER_MODE"] = "stub"  # no live Odoo in this check
    get_settings.cache_clear()  # get_settings() is lru_cached — must re-read the new profile
    from src.api.app import create_app

    return create_app()


def _seed(container, tenant: str, connection: str) -> None:
    """Seed a connection and a verified binding. Orders are adopted from the ERP."""
    from src.modules.reference.connections.domain.models import ErpConnection
    from src.modules.reference.tenancy.domain.models import BindingStatus, TenantConnectionBinding
    from src.shared.types import BindingId, ConnectionId, TenantId

    os.environ["SMOKE_ODOO_SECRET"] = "local-secret"  # resolved via EnvSecretStore (memory profile)
    container.connections.add(
        ErpConnection(
            connection_id=ConnectionId(connection),
            erp_type="ODOO",
            instance_label="Smoke Odoo",
            base_url="http://odoo:8069",
            credentials={"database": "odoo", "username": "admin"},
            secret_ref="env:SMOKE_ODOO_SECRET",
        )
    )
    container.bindings.add(
        TenantConnectionBinding(
            binding_id=BindingId(_id("bind")),
            tenant_id=TenantId(tenant),
            connection_id=ConnectionId(connection),
            erp_customer_id="CUST-1",
            status=BindingStatus.VERIFIED,
        )
    )


_GET_ORDER = """
query($id: String!) {
  order(orderId: $id) {
    orderId
    status
    lines { productKey quantity unitOfMeasure }
    timeline { status occurredAt }
  }
}
"""


def test_memory_profile_observes_order_and_reads_it() -> None:
    from fastapi.testclient import TestClient
    from src.modules.integration.erp.application.ports import ErpPartnerOrderLine
    from src.shared.types import TenantId

    app = _app("memory")
    tenant, connection, sku = _id("tnt"), _id("conn"), _id("SKU")
    _seed(app.state.container, tenant, connection)

    client = TestClient(app)
    assert client.get("/livez").status_code == 200

    order_id = app.state.container.order_service.observe_erp_order(
        tenant_id=TenantId(tenant),
        connection_id=connection,
        erp_order_id="S00042",
        client_reference="S00042",
        lines=[ErpPartnerOrderLine(product_key=sku, quantity="1", unit_price="10")],
        subsidiary_id="sub_demo",
    )
    app.state.container.drain()

    view = app.state.container.projections.get_reseller_view(tenant, order_id)
    assert view is not None
    assert view.status == "SENT_TO_ERP"

    # Through the actual GraphQL query resolver this time, not just the container — this
    # is what caught `OrderLineType(pos, pos, pos)` breaking under strawberry (types need
    # kwargs), which the container-only checks above never touch.
    resp = client.post(
        "/graphql/reseller",
        json={"query": _GET_ORDER, "variables": {"id": order_id}},
        headers={"x-tenant-id": tenant},
    )
    assert resp.status_code == 200
    gql_body = resp.json()
    assert gql_body.get("errors") is None, gql_body
    assert gql_body["data"]["order"]["status"] == "SENT_TO_ERP"
    assert gql_body["data"]["order"]["lines"][0]["productKey"] == sku
    assert gql_body["data"]["order"]["lines"][0]["quantity"] == 1.0


def test_postgres_profile_observes_order_and_leaves_it_for_the_worker() -> None:
    from src.modules.integration.erp.application.ports import ErpPartnerOrderLine
    from src.shared.types import TenantId

    app = _app("postgres")
    tenant, connection, sku = _id("tnt"), _id("conn"), _id("SKU")
    _seed(app.state.container, tenant, connection)
    assert app.state.container.bus is None

    order_id = app.state.container.order_service.observe_erp_order(
        tenant_id=TenantId(tenant),
        connection_id=connection,
        erp_order_id="S00042",
        client_reference="S00042",
        lines=[ErpPartnerOrderLine(product_key=sku, quantity="1", unit_price="10")],
        subsidiary_id="sub_demo",
    )

    try:
        # Nothing has processed it yet — no worker (item C) is running — so the event and
        # its outbox row exist, but the projection is still empty. That's the correct
        # handoff point.
        with _factory() as session:
            event_row = session.execute(
                text("SELECT event_type FROM events WHERE stream_id = :oid"), {"oid": order_id}
            ).fetchall()
            outbox_row = session.execute(
                text("SELECT published_at FROM outbox WHERE stream_id = :oid"), {"oid": order_id}
            ).fetchall()
        assert [r[0] for r in event_row] == ["OrderObserved"]
        assert len(outbox_row) == 1 and outbox_row[0][0] is None

        assert app.state.container.projections.get_reseller_view(tenant, order_id) is None
    finally:
        # This event/connection has no consumer of its own — item C's worker/relay would
        # otherwise pick up an unpublished outbox row and iterate a connection with a
        # fake secret_ref, crashing every reconcile/delivery attempt on real test data
        # left behind. Learned this the hard way; see aidlc-docs/audit.md.
        with _factory() as session, session.begin():
            session.execute(text("DELETE FROM outbox WHERE stream_id = :oid"), {"oid": order_id})
            session.execute(text("DELETE FROM events WHERE stream_id = :oid"), {"oid": order_id})
            # Also clean the projection, in case a worker happens to be running
            # concurrently against this same dev database and already consumed the event.
            session.execute(
                text("DELETE FROM order_status_history WHERE order_id = :oid"), {"oid": order_id}
            )
            session.execute(text("DELETE FROM orders WHERE order_id = :oid"), {"oid": order_id})
            session.execute(
                text("DELETE FROM tenant_connection_bindings WHERE connection_id = :cid"),
                {"cid": connection},
            )
            session.execute(
                text("DELETE FROM erp_connections WHERE connection_id = :cid"), {"cid": connection}
            )
