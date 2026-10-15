"""The composition root adopts an ERP sales order and the reseller projection shows it."""

from __future__ import annotations

import os

from src.composition import build_container
from src.modules.integration.erp.application.ports import ErpPartnerOrderLine
from src.modules.reference.connections.domain.models import ErpConnection
from src.modules.reference.tenancy.domain.models import BindingStatus, TenantConnectionBinding
from src.shared.types import BindingId, ConnectionId, TenantId


def test_container_observes_an_erp_order() -> None:
    os.environ["ODOO_SECRET"] = "local-secret"
    container = build_container()

    conn = ConnectionId("conn_odoo_local")
    container.connections.add(
        ErpConnection(
            connection_id=conn,
            erp_type="ODOO",
            instance_label="Local Odoo",
            base_url="http://odoo:8069",
            credentials={"database": "odoo", "username": "admin"},
            secret_ref="env:ODOO_SECRET",
        )
    )
    container.bindings.add(
        TenantConnectionBinding(
            binding_id=BindingId("bind_demo"),
            tenant_id=TenantId("tnt_demo"),
            connection_id=conn,
            erp_customer_id="CUST-1",
            status=BindingStatus.VERIFIED,
        )
    )

    order_id = container.order_service.observe_erp_order(
        tenant_id=TenantId("tnt_demo"),
        connection_id=str(conn),
        erp_order_id="S00042",
        client_reference="S00042",
        lines=[ErpPartnerOrderLine(product_key="ANVIL", quantity="2", unit_price="19.99")],
        subsidiary_id="sub_demo",
    )
    container.bus.run_until_empty()

    view = container.projections.get_reseller_view("tnt_demo", order_id)
    assert view is not None
    assert view.status == "SENT_TO_ERP"
    assert view.lines[0].product_key == "ANVIL"
