"""Unit tests for SapAdapter's pure logic and request-shaping, mocking the HTTP seam
(`_oauth_token`/`_request`/`_do_request`) rather than a live SAP system — these prove the
adapter's own decisions (idempotency, fail-closed org-structure/customer resolution,
which fields `fetch_status` reads), not SAP's actual behavior. Live verification against
a real SAP sandbox remains separately required before trusting this in production, per
`docs/erps/sap/README.md`.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest

from src.modules.integration.erp.application.ports import ErpTarget
from src.modules.integration.erp.infrastructure.sap_adapter import (
    SapAdapter,
    build_sap_order_items,
)

_ORG_CREDENTIALS = {
    "client_id": "client-x",
    "sales_order_type": "OR",
    "sales_organization": "1000",
    "distribution_channel": "10",
    "organization_division": "00",
}

_TARGET = ErpTarget(
    erp_type="SAP",
    base_url="https://sap.example.com/sap/opu/odata/sap/API_SALES_ORDER_SRV",
    credentials=_ORG_CREDENTIALS,
    secret="x",
)


def test_capabilities_are_declared() -> None:
    """ADR-0015: a declared, inspectable contract — not yet gated on, but real."""
    assert SapAdapter.capabilities == {"idempotency", "fail_closed_product", "partial_fulfillment"}


def test_build_sap_order_items_defaults_bad_quantity_to_one() -> None:
    items = build_sap_order_items({"lines": [{"product_key": "ANVIL", "quantity": "not-a-number"}]})
    assert items == [
        {
            "product_key": "ANVIL",
            "quantity": 1.0,
            "unit_of_measure": "",
            "unit_price": None,
            "currency": None,
        }
    ]


def test_build_sap_order_items_nets_price_against_flat_discount() -> None:
    """Same net-of-discount computation as Odoo's build_sale_order_lines, applied before
    writing the (LOW CONFIDENCE, approved) unit_price -> NetAmount mapping."""
    items = build_sap_order_items(
        {
            "lines": [
                {
                    "product_key": "ANVIL",
                    "quantity": 2,
                    "unit_of_measure": "EA",
                    "unit_price": {"amount": "19.99", "currency": "USD"},
                    "line_discount": {"amount": "2.00", "currency": "USD"},
                }
            ]
        }
    )
    assert items[0]["unit_price"] == pytest.approx(17.99)
    assert items[0]["currency"] == "USD"


def test_submit_is_idempotent_on_platform_order_id() -> None:
    """A retried submit for the same order must return the existing SAP order, not
    create a second one. The idempotency key is the platform order id (FR-A2), written
    to and searched on PurchaseOrderByCustomer."""
    calls: list[tuple[str, str, dict | None]] = []

    def fake_request(
        target: Any,
        token: str,
        method: str,
        path: str,
        *,
        params: dict | None = None,
        json_body: dict | None = None,
    ) -> Any:
        calls.append((method, path, params))
        if method == "GET" and path == "/A_SalesOrder":
            return {"d": {"results": [{"SalesOrder": "4500000099"}]}}
        raise AssertionError(f"should not reach {method} {path} once an existing order matches")

    adapter = SapAdapter()
    with (
        patch.object(SapAdapter, "_oauth_token", return_value="tok"),
        patch.object(SapAdapter, "_request", side_effect=fake_request),
    ):
        result = adapter.submit(_TARGET, {"order_id": "ord_123", "erp_customer_id": "5", "lines": []})

    assert result.success
    assert result.erp_order_id == "4500000099"
    assert calls == [
        (
            "GET",
            "/A_SalesOrder",
            {"$filter": "PurchaseOrderByCustomer eq 'ord_123'", "$format": "json"},
        )
    ]


def test_submit_creates_with_sold_to_party_direct_and_org_structure() -> None:
    """The customer is the binding's erp_customer_id sent as SoldToParty (FR-A1) — no
    name-based lookup — and the mandatory org-structure fields come from this
    connection's credentials, never invented."""
    created_body: dict[str, Any] = {}

    def fake_request(
        target: Any,
        token: str,
        method: str,
        path: str,
        *,
        params: dict | None = None,
        json_body: dict | None = None,
    ) -> Any:
        if method == "GET" and path == "/A_SalesOrder":
            return {"d": {"results": []}}
        if method == "POST" and path == "/A_SalesOrder":
            created_body.update(json_body or {})
            return {"d": {"SalesOrder": "4500000100"}}
        raise AssertionError(f"unexpected call: {method} {path}")

    adapter = SapAdapter()
    with (
        patch.object(SapAdapter, "_oauth_token", return_value="tok"),
        patch.object(SapAdapter, "_request", side_effect=fake_request),
    ):
        result = adapter.submit(
            _TARGET,
            {
                "order_id": "ord_2",
                "erp_customer_id": "5",
                "lines": [{"product_key": "ANVIL", "quantity": 2, "unit_of_measure": "EA"}],
            },
        )

    assert result.success
    assert result.erp_order_id == "4500000100"
    assert created_body["SoldToParty"] == "5"  # the erp_customer_id, used directly
    assert created_body["PurchaseOrderByCustomer"] == "ord_2"
    assert created_body["SalesOrderType"] == "OR"
    assert created_body["SalesOrganization"] == "1000"
    assert created_body["DistributionChannel"] == "10"
    assert created_body["OrganizationDivision"] == "00"
    assert created_body["to_Item"]["results"] == [
        {"Material": "ANVIL", "RequestedQuantity": 2.0, "RequestedQuantityUnit": "EA"}
    ]


def test_submit_fails_closed_without_an_erp_customer_id() -> None:
    """No binding -> no erp_customer_id -> terminal error, never a nameless auto-created
    customer (FR-A1)."""

    def fake_request(
        target: Any,
        token: str,
        method: str,
        path: str,
        *,
        params: dict | None = None,
        json_body: dict | None = None,
    ) -> Any:
        if method == "GET" and path == "/A_SalesOrder":
            return {"d": {"results": []}}
        raise AssertionError(f"must not proceed without a customer: {method} {path}")

    adapter = SapAdapter()
    with (
        patch.object(SapAdapter, "_oauth_token", return_value="tok"),
        patch.object(SapAdapter, "_request", side_effect=fake_request),
    ):
        result = adapter.submit(
            _TARGET, {"order_id": "ord_x", "lines": [{"product_key": "ANVIL", "quantity": 1}]}
        )

    assert not result.success
    assert result.terminal


def test_submit_fails_closed_without_org_structure_credentials() -> None:
    """Account-specific org-structure values must come from this connection's
    credentials — never invented when missing."""
    target = ErpTarget(
        erp_type="SAP",
        base_url="https://sap.example.com/sap/opu/odata/sap/API_SALES_ORDER_SRV",
        credentials={"client_id": "client-x"},  # no org-structure keys
        secret="x",
    )

    def fake_request(
        target: Any,
        token: str,
        method: str,
        path: str,
        *,
        params: dict | None = None,
        json_body: dict | None = None,
    ) -> Any:
        if method == "GET" and path == "/A_SalesOrder":
            return {"d": {"results": []}}
        raise AssertionError(f"must not create without org structure: {method} {path}")

    adapter = SapAdapter()
    with (
        patch.object(SapAdapter, "_oauth_token", return_value="tok"),
        patch.object(SapAdapter, "_request", side_effect=fake_request),
    ):
        result = adapter.submit(
            target,
            {
                "order_id": "ord_y",
                "erp_customer_id": "5",
                "lines": [{"product_key": "ANVIL", "quantity": 1}],
            },
        )

    assert not result.success
    assert result.terminal


def test_fetch_partner_orders_reads_client_reference_and_lines() -> None:
    def fake_request(
        target: Any,
        token: str,
        method: str,
        path: str,
        *,
        params: dict | None = None,
        json_body: dict | None = None,
    ) -> Any:
        assert method == "GET"
        assert path == "/A_SalesOrder"
        return {
            "d": {
                "results": [
                    {
                        "SalesOrder": "4500000001",
                        "PurchaseOrderByCustomer": "PO-7788",
                        "TransactionCurrency": "EUR",
                        "to_Item": {
                            "results": [
                                {"Material": "ANVIL", "RequestedQuantity": 3, "NetAmount": "19.99"}
                            ]
                        },
                    }
                ]
            }
        }

    adapter = SapAdapter()
    with (
        patch.object(SapAdapter, "_oauth_token", return_value="tok"),
        patch.object(SapAdapter, "_request", side_effect=fake_request),
    ):
        orders = adapter.fetch_partner_orders(_TARGET, "5")

    assert len(orders) == 1
    assert orders[0].erp_order_id == "4500000001"
    assert orders[0].client_reference == "PO-7788"
    assert orders[0].lines[0].product_key == "ANVIL"
    assert orders[0].lines[0].quantity == "3"
    assert orders[0].lines[0].unit_price == "19.99"
    assert orders[0].lines[0].currency == "EUR"


def test_fetch_status_returns_the_three_header_fields() -> None:
    def fake_request(
        target: Any,
        token: str,
        method: str,
        path: str,
        *,
        params: dict | None = None,
        json_body: dict | None = None,
    ) -> Any:
        assert params == {
            "$select": "OverallSDProcessStatus,OverallSDDocumentRejectionSts,OverallBillingStatus",
            "$format": "json",
        }
        return {
            "d": {
                "OverallSDProcessStatus": "C",
                "OverallSDDocumentRejectionSts": "",
                "OverallBillingStatus": "C",
            }
        }

    adapter = SapAdapter()
    with (
        patch.object(SapAdapter, "_oauth_token", return_value="tok"),
        patch.object(SapAdapter, "_request", side_effect=fake_request),
    ):
        fields = adapter.fetch_status(_TARGET, "4500000001")

    assert fields == {
        "overall_sd_process_status": "C",
        "overall_sd_document_rejection_status": "",
        "overall_billing_status": "C",
    }


def test_fetch_status_returns_none_when_order_not_found() -> None:
    adapter = SapAdapter()
    with (
        patch.object(SapAdapter, "_oauth_token", return_value="tok"),
        patch.object(SapAdapter, "_request", return_value={"d": None}),
    ):
        assert adapter.fetch_status(_TARGET, "nope") is None


def test_fetch_shipments_returns_empty_without_a_configured_service_url() -> None:
    """TODO-gated: the Outbound Delivery service root is account-specific and must not
    be guessed from the Sales Order service's base_url."""
    adapter = SapAdapter()
    with patch.object(SapAdapter, "_oauth_token", return_value="tok"):
        assert adapter.fetch_shipments(_TARGET, "4500000001") == []


def test_fetch_invoices_returns_empty_without_a_configured_service_url() -> None:
    adapter = SapAdapter()
    with patch.object(SapAdapter, "_oauth_token", return_value="tok"):
        assert adapter.fetch_invoices(_TARGET, "4500000001") == []


def test_fetch_shipments_reads_goods_issued_deliveries() -> None:
    target = ErpTarget(
        erp_type="SAP",
        base_url="https://sap.example.com/sap/opu/odata/sap/API_SALES_ORDER_SRV",
        credentials={
            **_ORG_CREDENTIALS,
            "outbound_delivery_service_url": "https://sap.example.com/.../API_OUTBOUND_DELIVERY_SRV",
        },
        secret="x",
    )

    def fake_do_request(
        target: Any,
        token: str,
        method: str,
        url: str,
        *,
        params: dict | None = None,
        json_body: dict | None = None,
    ) -> Any:
        assert url.endswith("/A_OutbDeliveryItem")
        return {
            "d": {
                "results": [
                    {
                        "DeliveryDocument": "80000001",
                        "Material": "ANVIL",
                        "ActualDeliveryQuantity": 2,
                        "to_DeliveryDocumentHeader": {"GoodsMovementStatus": "C"},
                    },
                    {
                        "DeliveryDocument": "80000002",
                        "Material": "ANVIL",
                        "ActualDeliveryQuantity": 5,
                        "to_DeliveryDocumentHeader": {"GoodsMovementStatus": ""},
                    },
                ]
            }
        }

    adapter = SapAdapter()
    with (
        patch.object(SapAdapter, "_oauth_token", return_value="tok"),
        patch.object(SapAdapter, "_do_request", side_effect=fake_do_request),
    ):
        shipments = adapter.fetch_shipments(target, "4500000001")

    assert len(shipments) == 1
    assert shipments[0].erp_shipment_id == "80000001"
    assert shipments[0].lines[0].product_key == "ANVIL"
    assert shipments[0].lines[0].quantity == "2"


def test_cancel_fails_closed_without_a_rejection_reason_code() -> None:
    """Account-specific rejection reason codes must come from this connection's
    credentials — never invented when missing."""
    adapter = SapAdapter()
    result = adapter.cancel(_TARGET, "4500000001")
    assert not result.success
    assert result.terminal


def test_cancel_patches_every_item_with_the_configured_rejection_reason() -> None:
    target = ErpTarget(
        erp_type="SAP",
        base_url="https://sap.example.com/sap/opu/odata/sap/API_SALES_ORDER_SRV",
        credentials={**_ORG_CREDENTIALS, "rejection_reason_code": "08"},
        secret="x",
    )
    patched: list[tuple[str, dict | None]] = []

    def fake_request(
        target: Any,
        token: str,
        method: str,
        path: str,
        *,
        params: dict | None = None,
        json_body: dict | None = None,
    ) -> Any:
        if method == "GET":
            return {"d": {"to_Item": {"results": [{"SalesOrderItem": "10"}, {"SalesOrderItem": "20"}]}}}
        if method == "PATCH":
            patched.append((path, json_body))
            return None
        raise AssertionError(f"unexpected call: {method} {path}")

    adapter = SapAdapter()
    with (
        patch.object(SapAdapter, "_oauth_token", return_value="tok"),
        patch.object(SapAdapter, "_request", side_effect=fake_request),
    ):
        result = adapter.cancel(target, "4500000001")

    assert result.success
    assert len(patched) == 2
    assert all(body == {"ReasonForRejection": "08"} for _, body in patched)
