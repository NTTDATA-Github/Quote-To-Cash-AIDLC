"""Unit tests for JsonPlaceholderDemoErpAdapter's pure logic and request-shaping,
mocking the HTTP seam (_request) rather than the live public API — these prove the
adapter's own decisions (idempotency search, fail-closed customer resolution, what
status_mapping.py's mapper is handed), not jsonplaceholder.typicode.com's actual
behavior. Live verification against the real public API, or a real backing account,
remains separately required before trusting this in production, per
docs/erps/jsonplaceholder-demo-erp/README.md.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

from src.modules.integration.erp.application.ports import ErpTarget
from src.modules.integration.erp.infrastructure.jsonplaceholder_demo_erp_adapter import (
    JsonPlaceholderDemoErpAdapter,
    build_post_payload,
)

_TARGET = ErpTarget(
    erp_type="JSONPLACEHOLDER_DEMO_ERP",
    base_url="https://jsonplaceholder.typicode.com",
    credentials={},
    secret="",
)


def test_capabilities_are_declared() -> None:
    """ADR-0015: only idempotency is real here — no product catalog, tax, uom,
    multi-currency, or shipment/invoice document exists in this ERP's public schema."""
    assert JsonPlaceholderDemoErpAdapter.capabilities == {"idempotency"}


def test_build_post_payload_applies_the_approved_name_mapping_when_present() -> None:
    """Approved mapping (96% confidence): canonical end_customer_name -> this ERP's
    "name" field."""
    payload = build_post_payload(
        {"order_id": "ord_1", "client_reference": "PO-9", "end_customer_name": "Acme Downstream"}
    )
    assert payload["name"] == "Acme Downstream"
    assert payload["title"] == "ord_1"


def test_build_post_payload_omits_name_when_absent() -> None:
    """read_payload does not populate end_customer_name today — omitted, not sent as
    an empty string, same graceful-degradation reasoning as Odoo's unmatched UoM/tax."""
    payload = build_post_payload({"order_id": "ord_2", "client_reference": "PO-10"})
    assert "name" not in payload


def test_build_post_payload_serializes_lines_as_json_text() -> None:
    import json

    payload = build_post_payload(
        {
            "order_id": "ord_3",
            "lines": [{"product_key": "ANVIL", "quantity": 2, "unit_of_measure": "EA"}],
        }
    )
    body = json.loads(payload["body"])
    assert body["lines"] == [{"product_key": "ANVIL", "quantity": "2", "unit_of_measure": "EA"}]


def test_submit_fails_closed_without_an_erp_customer_id() -> None:
    """No binding -> no erp_customer_id -> terminal error, never a silent create
    (same FR-A1 reasoning as Odoo's partner_id)."""

    def fake_request(target: Any, method: str, path: str, body: dict | None = None) -> Any:
        raise AssertionError(f"must not call the API without a customer id: {method} {path}")

    adapter = JsonPlaceholderDemoErpAdapter()
    with patch.object(JsonPlaceholderDemoErpAdapter, "_request", side_effect=fake_request):
        result = adapter.submit(_TARGET, {"order_id": "ord_x", "lines": []})

    assert not result.success
    assert result.terminal


def test_submit_fails_closed_on_unknown_customer_not_silent_auto_create() -> None:
    def fake_request(target: Any, method: str, path: str, body: dict | None = None) -> Any:
        if path == "/users/999":
            return None  # no such user
        raise AssertionError(f"unexpected call: {method} {path}")

    adapter = JsonPlaceholderDemoErpAdapter()
    with patch.object(JsonPlaceholderDemoErpAdapter, "_request", side_effect=fake_request):
        result = adapter.submit(
            _TARGET, {"order_id": "ord_1", "erp_customer_id": "999", "lines": []}
        )

    assert not result.success
    assert result.terminal
    assert "999" in (result.error or "")


def test_submit_is_idempotent_on_title_match() -> None:
    """A retried submit for the same order must return the existing post, not create a
    second one — the idempotency key is the platform order id (FR-A2), matched against
    title (same reasoning as Odoo's client_order_ref search)."""
    calls: list[tuple[str, str]] = []

    def fake_request(target: Any, method: str, path: str, body: dict | None = None) -> Any:
        calls.append((method, path))
        if path == "/users/5":
            return {"id": 5}
        if path == "/posts?userId=5":
            return [{"id": 77, "title": "ord_123"}]
        raise AssertionError(f"should not reach {method} {path} once title matches")

    adapter = JsonPlaceholderDemoErpAdapter()
    with patch.object(JsonPlaceholderDemoErpAdapter, "_request", side_effect=fake_request):
        result = adapter.submit(
            _TARGET, {"order_id": "ord_123", "erp_customer_id": "5", "lines": []}
        )

    assert result.success
    assert result.erp_order_id == "77"
    assert ("POST", "/posts") not in calls


def test_submit_creates_a_post_with_userid_and_approved_name_mapping() -> None:
    created: dict[str, Any] = {}

    def fake_request(target: Any, method: str, path: str, body: dict | None = None) -> Any:
        if path == "/users/5":
            return {"id": 5}
        if path == "/posts?userId=5":
            return []
        if method == "POST" and path == "/posts":
            created.update(body or {})
            return {"id": 101}
        raise AssertionError(f"unexpected call: {method} {path}")

    adapter = JsonPlaceholderDemoErpAdapter()
    with patch.object(JsonPlaceholderDemoErpAdapter, "_request", side_effect=fake_request):
        result = adapter.submit(
            _TARGET,
            {
                "order_id": "ord_4",
                "erp_customer_id": "5",
                "end_customer_name": "Acme Downstream",
                "lines": [{"product_key": "ANVIL", "quantity": 1}],
            },
        )

    assert result.success
    assert result.erp_order_id == "101"
    assert created["userId"] == 5
    assert created["title"] == "ord_4"
    assert created["name"] == "Acme Downstream"


def test_fetch_status_returns_the_raw_status_field() -> None:
    """status_mapping.py's _map_jsonplaceholder_demo_erp still maps every value to None
    (TODO, account-specific) — this only proves fetch_status reads the real,
    documented GET /posts/{id} endpoint and hands back what it finds."""

    def fake_request(target: Any, method: str, path: str, body: dict | None = None) -> Any:
        assert (method, path) == ("GET", "/posts/42")
        return {"id": 42, "status": "whatever-this-account-calls-it"}

    adapter = JsonPlaceholderDemoErpAdapter()
    with patch.object(JsonPlaceholderDemoErpAdapter, "_request", side_effect=fake_request):
        fields = adapter.fetch_status(_TARGET, "42")

    assert fields == {"status": "whatever-this-account-calls-it"}


def test_fetch_status_returns_none_when_post_not_found() -> None:
    adapter = JsonPlaceholderDemoErpAdapter()
    with patch.object(JsonPlaceholderDemoErpAdapter, "_request", return_value=None):
        assert adapter.fetch_status(_TARGET, "999") is None


def test_fetch_partner_orders_parses_lines_from_body_json() -> None:
    import json

    def fake_request(target: Any, method: str, path: str, body: dict | None = None) -> Any:
        assert path == "/posts?userId=5"
        return [
            {
                "id": 7,
                "title": "ord_1",
                "body": json.dumps(
                    {
                        "client_reference": "PO-1",
                        "lines": [{"product_key": "ANVIL", "quantity": "2"}],
                    }
                ),
            }
        ]

    adapter = JsonPlaceholderDemoErpAdapter()
    with patch.object(JsonPlaceholderDemoErpAdapter, "_request", side_effect=fake_request):
        orders = adapter.fetch_partner_orders(_TARGET, "5")

    assert len(orders) == 1
    assert orders[0].erp_order_id == "7"
    assert orders[0].client_reference == "PO-1"
    assert orders[0].lines[0].product_key == "ANVIL"


def test_fetch_partner_orders_skips_a_post_whose_body_is_not_our_json_shape() -> None:
    """A post whose body doesn't parse as our line shape (e.g. the public sandbox's
    own lorem-ipsum seed data) is skipped, not adopted as an empty order — same "no
    recognizable product code -> skip" reasoning Odoo applies per line."""

    def fake_request(target: Any, method: str, path: str, body: dict | None = None) -> Any:
        return [{"id": 1, "title": "lorem", "body": "quia et suscipit\nsuscipit..."}]

    adapter = JsonPlaceholderDemoErpAdapter()
    with patch.object(JsonPlaceholderDemoErpAdapter, "_request", side_effect=fake_request):
        orders = adapter.fetch_partner_orders(_TARGET, "5")

    assert orders == []


def test_fetch_shipments_and_fetch_invoices_return_empty() -> None:
    """No shipment/invoice document exists in this ERP's public schema."""
    adapter = JsonPlaceholderDemoErpAdapter()
    assert adapter.fetch_shipments(_TARGET, "1") == []
    assert adapter.fetch_invoices(_TARGET, "1") == []


def test_cancel_deletes_the_post() -> None:
    def fake_request(target: Any, method: str, path: str, body: dict | None = None) -> Any:
        assert (method, path) == ("DELETE", "/posts/42")
        return {}

    adapter = JsonPlaceholderDemoErpAdapter()
    with patch.object(JsonPlaceholderDemoErpAdapter, "_request", side_effect=fake_request):
        result = adapter.cancel(_TARGET, "42")

    assert result.success
    assert result.erp_order_id == "42"
