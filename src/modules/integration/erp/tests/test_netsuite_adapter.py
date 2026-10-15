"""Unit tests for NetSuiteAdapter's pure logic and request-shaping, mocking the HTTP seam
(`_request`) rather than a live NetSuite — these prove the adapter's own decisions
(idempotency on externalId, fail-closed item/customer resolution, what fetch_status reads,
how fulfillments/invoices are read via SuiteQL). End-to-end behavior over real OAuth-signed
HTTP is proven separately against the in-process mock in
`tests/integration/test_netsuite_adapter_against_mock.py`.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import patch

import pytest

from src.modules.integration.erp.application.ports import ErpTarget
from src.modules.integration.erp.infrastructure.netsuite_adapter import (
    NetSuiteAdapter,
    build_salesorder_lines,
    oauth1_authorization_header,
    parse_record_id_from_location,
)

_SECRET = json.dumps({"consumer_secret": "cs", "token_secret": "ts"})
_TARGET = ErpTarget(
    erp_type="NETSUITE",
    base_url="https://acct.suitetalk.api.netsuite.com",
    credentials={"account_id": "ACCT", "consumer_key": "ck", "token_id": "ti"},
    secret=_SECRET,
)


def test_capabilities_are_declared() -> None:
    assert NetSuiteAdapter.capabilities == {
        "tax",
        "uom",
        "idempotency",
        "fail_closed_product",
        "partial_fulfillment",
    }


def test_oauth1_header_is_deterministic_and_wellformed() -> None:
    kwargs = {
        "account_id": "tstdrv123",
        "consumer_key": "ck",
        "token_id": "ti",
        "consumer_secret": "cs",
        "token_secret": "ts",
        "nonce": "fixednonce1234567890",
        "timestamp": "1700000000",
    }
    header = oauth1_authorization_header("GET", "https://x/y?a=1", **kwargs)
    again = oauth1_authorization_header("GET", "https://x/y?a=1", **kwargs)
    assert header == again  # deterministic for fixed nonce/timestamp
    assert header.startswith('OAuth realm="TSTDRV123"')  # realm upper-cased
    assert 'oauth_signature_method="HMAC-SHA256"' in header
    assert 'oauth_consumer_key="ck"' in header
    assert "oauth_signature=" in header
    # the signature is sensitive to the signing key
    other = oauth1_authorization_header(
        "GET", "https://x/y?a=1", **{**kwargs, "token_secret": "different"}
    )
    assert other != header


def test_parse_record_id_from_location() -> None:
    assert (
        parse_record_id_from_location(
            "https://acct.suitetalk.api.netsuite.com/services/rest/record/v1/salesOrder/789"
        )
        == "789"
    )
    assert parse_record_id_from_location("/services/rest/record/v1/salesOrder/42/") == "42"
    assert parse_record_id_from_location(None) is None
    assert parse_record_id_from_location("") is None


def test_build_salesorder_lines_defaults_bad_quantity_to_one() -> None:
    lines = build_salesorder_lines({"lines": [{"product_key": "ANVIL", "quantity": "nope"}]})
    assert lines == [
        {
            "product_key": "ANVIL",
            "quantity": 1.0,
            "unit_of_measure": "",
            "rate": None,
            "currency": None,
            "tax_codes": [],
        }
    ]


def test_build_salesorder_lines_nets_rate_against_flat_discount() -> None:
    lines = build_salesorder_lines(
        {
            "lines": [
                {
                    "product_key": "ANVIL",
                    "quantity": 2,
                    "unit_of_measure": "EA",
                    "unit_price": {"amount": "19.99", "currency": "USD"},
                    "line_discount": {"amount": "2.00", "currency": "USD"},
                    "tax_rates": [{"code": "VAT", "rate": "0.20", "inclusive": False}],
                }
            ]
        }
    )
    assert lines[0]["rate"] == pytest.approx(17.99)
    assert lines[0]["currency"] == "USD"
    assert lines[0]["tax_codes"] == ["VAT"]


def _ok(status: int, body: dict[str, Any] | None = None, headers: dict[str, str] | None = None):
    return (status, headers or {}, body)


def test_submit_is_idempotent_on_external_id() -> None:
    """A retried submit for the same order returns the existing NetSuite order (found by
    externalId), never creating a second one."""
    calls: list[tuple[str, str]] = []

    def fake_request(target, method, path, *, body=None, extra_headers=None):
        calls.append((method, path))
        if method == "GET" and path.endswith("/salesOrder/eid:ord_123"):
            return _ok(200, {"id": "555", "tranId": "SO555"})
        raise AssertionError(f"must not reach {method} {path} when the order already exists")

    adapter = NetSuiteAdapter()
    with patch.object(NetSuiteAdapter, "_request", side_effect=fake_request):
        result = adapter.submit(
            _TARGET, {"order_id": "ord_123", "erp_customer_id": "101", "lines": []}
        )

    assert result.success
    assert result.erp_order_id == "555"
    assert calls == [("GET", "/services/rest/record/v1/salesOrder/eid:ord_123")]


def test_submit_creates_as_customer_and_parses_location() -> None:
    created: dict[str, Any] = {}

    def fake_request(target, method, path, *, body=None, extra_headers=None):
        if method == "GET" and "eid:" in path:
            return _ok(404)
        if method == "POST" and path.endswith("/suiteql"):
            query = body["q"]
            if "FROM item WHERE itemid = 'ANVIL'" in query:
                return _ok(200, {"items": [{"id": "201"}]})
            return _ok(200, {"items": []})  # uom/tax graceful-degradation lookups
        if method == "POST" and path.endswith("/salesOrder"):
            created.update(body)
            return _ok(204, None, {"Location": "/services/rest/record/v1/salesOrder/777"})
        raise AssertionError(f"unexpected call {method} {path}")

    adapter = NetSuiteAdapter()
    with patch.object(NetSuiteAdapter, "_request", side_effect=fake_request):
        result = adapter.submit(
            _TARGET,
            {
                "order_id": "ord_2",
                "erp_customer_id": "101",
                "lines": [{"product_key": "ANVIL", "quantity": 2}],
            },
        )

    assert result.success
    assert result.erp_order_id == "777"
    assert created["entity"] == {"id": "101"}  # placed AS the binding's customer (FR-A1)
    assert created["externalId"] == "ord_2"  # idempotency key (FR-A2)
    assert created["item"]["items"][0]["item"] == {"id": "201"}
    assert created["item"]["items"][0]["quantity"] == 2.0


def test_submit_fails_closed_without_a_customer_id() -> None:
    def fake_request(target, method, path, *, body=None, extra_headers=None):
        if method == "GET" and "eid:" in path:
            return _ok(404)
        raise AssertionError("must not proceed without a customer")

    adapter = NetSuiteAdapter()
    with patch.object(NetSuiteAdapter, "_request", side_effect=fake_request):
        result = adapter.submit(
            _TARGET, {"order_id": "o", "lines": [{"product_key": "ANVIL", "quantity": 1}]}
        )

    assert not result.success
    assert result.terminal


def test_submit_fails_closed_on_unknown_item_not_silent_create() -> None:
    def fake_request(target, method, path, *, body=None, extra_headers=None):
        if method == "GET" and "eid:" in path:
            return _ok(404)
        if method == "POST" and path.endswith("/suiteql"):
            return _ok(200, {"items": []})  # item not found
        raise AssertionError(f"must not create anything: {method} {path}")

    adapter = NetSuiteAdapter()
    with patch.object(NetSuiteAdapter, "_request", side_effect=fake_request):
        result = adapter.submit(
            _TARGET,
            {
                "order_id": "o3",
                "erp_customer_id": "101",
                "lines": [{"product_key": "TYPO", "quantity": 1}],
            },
        )

    assert not result.success
    assert result.terminal
    assert "TYPO" in (result.error or "")


def test_submit_terminal_on_malformed_secret() -> None:
    bad_target = ErpTarget(
        erp_type="NETSUITE",
        base_url="https://acct",
        credentials={"account_id": "A", "consumer_key": "ck", "token_id": "ti"},
        secret="not-json",
    )
    # the secret is parsed before any socket is opened, so a bad secret must fail terminally
    # without ever hitting the network (urlopen must not be called)
    with patch("urllib.request.urlopen", side_effect=AssertionError("no HTTP must be attempted")):
        result = NetSuiteAdapter().submit(
            bad_target, {"order_id": "o", "erp_customer_id": "101", "lines": []}
        )
    assert not result.success
    assert result.terminal


def test_fetch_status_reads_status_and_order_status() -> None:
    def fake_request(target, method, path, *, body=None, extra_headers=None):
        return _ok(200, {"status": "Pending Fulfillment", "orderStatus": "_pendingFulfillment"})

    with patch.object(NetSuiteAdapter, "_request", side_effect=fake_request):
        fields = NetSuiteAdapter().fetch_status(_TARGET, "777")

    assert fields == {"status": "Pending Fulfillment", "order_status": "_pendingFulfillment"}


def test_fetch_status_reads_nested_refname_object() -> None:
    def fake_request(target, method, path, *, body=None, extra_headers=None):
        return _ok(
            200, {"status": {"id": "B", "refName": "Pending Fulfillment"}, "orderStatus": ""}
        )

    with patch.object(NetSuiteAdapter, "_request", side_effect=fake_request):
        fields = NetSuiteAdapter().fetch_status(_TARGET, "777")

    assert fields == {"status": "Pending Fulfillment", "order_status": ""}


def test_fetch_status_none_when_not_found() -> None:
    with patch.object(NetSuiteAdapter, "_request", side_effect=lambda *a, **k: _ok(404)):
        assert NetSuiteAdapter().fetch_status(_TARGET, "nope") is None


def test_fetch_shipments_reads_fulfillments_and_abs_quantities() -> None:
    def fake_request(target, method, path, *, body=None, extra_headers=None):
        query = body["q"]
        if "type = 'ItemShip' AND createdfrom = 777" in query:
            return _ok(200, {"items": [{"id": "900", "tranid": "IF900"}]})
        if "tl.transaction = 900" in query:
            return _ok(200, {"items": [{"itemid": "ANVIL", "quantity": -2}]})
        return _ok(200, {"items": []})

    with patch.object(NetSuiteAdapter, "_request", side_effect=fake_request):
        shipments = NetSuiteAdapter().fetch_shipments(_TARGET, "777")

    assert len(shipments) == 1
    assert shipments[0].erp_shipment_id == "900"
    assert shipments[0].proof_of_delivery == "IF900"
    assert shipments[0].lines[0].product_key == "ANVIL"
    assert shipments[0].lines[0].quantity == "2"  # abs of NetSuite's negative outbound qty


def test_fetch_invoices_reads_posted_invoices() -> None:
    def fake_request(target, method, path, *, body=None, extra_headers=None):
        query = body["q"]
        if "type = 'CustInvc' AND createdfrom = 777" in query:
            return _ok(200, {"items": [{"id": "950", "tranid": "INV950"}]})
        if "tl.transaction = 950" in query:
            return _ok(200, {"items": [{"itemid": "ANVIL", "quantity": 3}]})
        return _ok(200, {"items": []})

    with patch.object(NetSuiteAdapter, "_request", side_effect=fake_request):
        invoices = NetSuiteAdapter().fetch_invoices(_TARGET, "777")

    assert len(invoices) == 1
    assert invoices[0].erp_invoice_id == "950"
    assert invoices[0].number == "INV950"
    assert invoices[0].lines[0].product_key == "ANVIL"
    assert invoices[0].lines[0].quantity == "3"


def test_cancel_deletes_the_sales_order() -> None:
    seen: list[tuple[str, str]] = []

    def fake_request(target, method, path, *, body=None, extra_headers=None):
        seen.append((method, path))
        return _ok(204)

    with patch.object(NetSuiteAdapter, "_request", side_effect=fake_request):
        result = NetSuiteAdapter().cancel(_TARGET, "777")

    assert result.success
    assert seen == [("DELETE", "/services/rest/record/v1/salesOrder/777")]


def test_cancel_treats_404_as_already_gone() -> None:
    with patch.object(NetSuiteAdapter, "_request", side_effect=lambda *a, **k: _ok(404)):
        result = NetSuiteAdapter().cancel(_TARGET, "gone")
    assert result.success
