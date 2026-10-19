"""Integration tests for the Phase 3 Postgres adapters (Phase 3 item A).

Requires a reachable Postgres with migrations applied. Self-skips (not a failure) when
`sqlalchemy`/`psycopg2` aren't installed or `DATABASE_URL` isn't reachable — this sandbox
has neither. Run for real via:
    docker compose up -d postgres && alembic upgrade head
    pytest tests/integration/test_postgres_adapters.py
"""

from __future__ import annotations

import uuid

import pytest

pytest.importorskip("sqlalchemy")

from sqlalchemy import text  # noqa: E402
from src.modules.integration.webhooks_inbound.infrastructure.postgres import (  # noqa: E402
    PostgresDedupStore,
    PostgresOrderLocator,
)
from src.modules.reference.connections.domain.models import (  # noqa: E402
    ConnectionStatus,
    ErpConnection,
)
from src.modules.reference.connections.infrastructure.postgres import (  # noqa: E402
    PostgresConnectionRepository,
)
from src.modules.reference.tenancy.domain.errors import BindingConflict  # noqa: E402
from src.modules.reference.tenancy.domain.models import TenantConnectionBinding  # noqa: E402
from src.modules.reference.tenancy.infrastructure.postgres import (  # noqa: E402
    PostgresBindingRepository,
)
from src.modules.sales.ordering.domain.models import OrderState  # noqa: E402
from src.modules.sales.ordering.projections.postgres_store import (  # noqa: E402
    PostgresOrderProjectionStore,
)
from src.modules.sales.ordering.projections.read_models import OrderLineView  # noqa: E402
from src.shared.persistence.engine import get_session_factory  # noqa: E402
from src.shared.types import BindingId, ConnectionId, OrderId, TenantId  # noqa: E402

try:
    _factory = get_session_factory()
    with _factory() as _probe:
        _probe.execute(text("SELECT 1"))
except Exception as exc:  # pragma: no cover - environment-dependent
    pytest.skip(f"Postgres not reachable: {exc}", allow_module_level=True)


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


# Every row this file creates gets tracked here and deleted in `_cleanup` below. Rows
# left behind aren't just clutter: a worker's reconcile scheduler and delivery consumer
# iterate ALL active connections, so a stray one with a fake secret_ref makes the worker
# raise on every poll. (Learned the hard way — see aidlc-docs/audit.md.)
_created_connection_ids: list[str] = []
_created_order_ids: list[str] = []
_created_dedup_keys: list[str] = []


@pytest.fixture(autouse=True, scope="module")
def _cleanup():
    yield
    with _factory() as session, session.begin():
        if _created_order_ids:
            session.execute(
                text("DELETE FROM order_status_history WHERE order_id = ANY(:ids)"),
                {"ids": _created_order_ids},
            )
            session.execute(
                text("DELETE FROM orders WHERE order_id = ANY(:ids)"), {"ids": _created_order_ids}
            )
        if _created_connection_ids:
            session.execute(
                text("DELETE FROM tenant_connection_bindings WHERE connection_id = ANY(:ids)"),
                {"ids": _created_connection_ids},
            )
            session.execute(
                text("DELETE FROM erp_connections WHERE connection_id = ANY(:ids)"),
                {"ids": _created_connection_ids},
            )
        if _created_dedup_keys:
            session.execute(
                text("DELETE FROM processed_events WHERE event_id = ANY(:ids)"),
                {"ids": _created_dedup_keys},
            )


def _make_connection() -> ErpConnection:
    """items.owning_connection_id and tenant_connection_bindings.connection_id are both
    FKs to erp_connections (migration 0001) — tests that reference a connection must
    create a real one first, not just mint a random id."""
    conn = ErpConnection(
        connection_id=ConnectionId(_id("conn")),
        erp_type="ODOO",
        instance_label="Test Odoo",
        base_url="http://odoo:8069",
        credentials={"database": "odoo", "username": "admin"},
        secret_ref="arn:secret:test",
    )
    PostgresConnectionRepository(_factory).add(conn)
    _created_connection_ids.append(str(conn.connection_id))
    return conn


def test_connection_repository_roundtrip() -> None:
    repo = PostgresConnectionRepository(_factory)
    conn = _make_connection()
    assert repo.get(conn.connection_id) == conn
    assert conn in repo.list_active()


def test_connection_repository_update_persists_status_and_label() -> None:
    repo = PostgresConnectionRepository(_factory)
    conn = _make_connection()
    conn.status = ConnectionStatus.PAUSED
    conn.instance_label = "Renamed Odoo"
    repo.update(conn)
    reloaded = repo.get(conn.connection_id)
    assert reloaded is not None
    assert reloaded.status is ConnectionStatus.PAUSED
    assert reloaded.instance_label == "Renamed Odoo"


def test_binding_repository_enforces_uniqueness_at_db() -> None:
    repo = PostgresBindingRepository(_factory)
    tenant = TenantId(_id("tnt"))
    connection = _make_connection().connection_id
    binding = TenantConnectionBinding(
        binding_id=BindingId(_id("bind")),
        tenant_id=tenant,
        connection_id=connection,
        erp_customer_id="cust_1",
    )
    repo.add(binding)
    assert repo.find_by_tenant_and_connection(tenant, connection) == binding

    dup = TenantConnectionBinding(
        binding_id=BindingId(_id("bind")),
        tenant_id=tenant,
        connection_id=connection,
        erp_customer_id="cust_2",
    )
    with pytest.raises(BindingConflict):
        repo.add(dup)


def test_order_projection_store_reseller_view_excludes_erp_identity() -> None:
    store = PostgresOrderProjectionStore(_factory)
    order_id = _id("ord")
    tenant = _id("tnt")
    connection = _id("conn")
    _created_order_ids.append(order_id)

    store.create(order_id, tenant, "PO-1", [OrderLineView("sku-1", 2.0, "EA")])
    store.set_owning_connection(order_id, connection)
    store.set_erp_order_id(order_id, "S00099")
    store.set_state(order_id, OrderState.CONFIRMED, "2026-09-27T00:00:00+00:00")

    reseller = store.get_reseller_view(tenant, order_id)
    assert reseller is not None
    assert reseller.status == "CONFIRMED"
    # _line_from_json falls back line_id to product_key when the stored value is empty
    # (store.create was called with no explicit line_id above) — this is the documented
    # read-side fallback, not a round-trip bug.
    assert reseller.lines == [OrderLineView("sku-1", 2.0, "EA", line_id="sku-1")]
    assert not hasattr(reseller, "erp_order_id")  # FR-19: reseller view never carries ERP identity

    operator = store.get_operator_view(order_id)
    assert operator is not None
    assert operator.erp_order_id == "S00099"
    assert operator.owning_connection_id == connection
    assert len(operator.timeline) == 1

    assert store.get_reseller_view(TenantId(_id("other-tenant")), order_id) is None  # fail-closed


def test_webhook_dedup_and_locator_see_the_projection_store() -> None:
    dedup = PostgresDedupStore(_factory)
    locator = PostgresOrderLocator(_factory)
    key = _id("evt")
    _created_dedup_keys.append(key)
    assert not dedup.seen(key)
    dedup.mark(key)
    assert dedup.seen(key)

    store = PostgresOrderProjectionStore(_factory)
    order_id = _id("ord")
    connection = ConnectionId(_id("conn"))
    _created_order_ids.append(order_id)
    store.create(order_id, _id("tnt"), "PO-2", [])
    store.set_owning_connection(order_id, str(connection))
    store.set_erp_order_id(order_id, "S00100")

    assert locator.find_order(connection, "S00100") == OrderId(order_id)
    assert locator.find_order(connection, "no-such-order") is None
