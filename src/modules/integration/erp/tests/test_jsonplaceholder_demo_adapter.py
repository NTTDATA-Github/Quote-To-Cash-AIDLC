"""Unit tests for JsonPlaceholderDemoAdapter's pure logic and request-shaping, mocking
`_request` (the HTTP seam) rather than a live JSONPlaceholder — same pattern as
`test_odoo_adapter.py`. Never hits the real public API.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest

from src.modules.integration.erp.application.ports import ErpTarget
from src.modules.integration.erp.infrastructure.jsonplaceholder_demo_adapter import (
    JsonPlaceholderDemoAdapter,
    build_todo_payload,
)

_TARGET = ErpTarget(
    erp_type="JSONPLACEHOLDER_DEMO",
    base_url="https://jsonplaceholder.typicode.com",
    credentials={},
    secret="",
)


def test_capabilities_are_declared_empty() -> None:
    """ADR-0015: declared, inspectable, and honest about having no real guarantees here
    (see the class docstring/comment for why)."""
    assert JsonPlaceholderDemoAdapter.capabilities == frozenset()


def test_build_todo_payload_wires_the_approved_mapping() -> None:
    """name -> end_customer_name (confidence 95%), the human-approved mapping — the only
    thing this test locks in about field *meaning*; everything else here is a platform
    convention, not a business decision."""
    payload = build_todo_payload(
        {
            "order_id": "ord_1",
            "parties": {"end_customer_name": "Acme Downstream"},
        }
    )
    assert payload == {
        "title": "ord_1",
        "completed": False,
        "name": "Acme Downstream",
    }


def test_build_todo_payload_omits_name_when_no_end_customer_name() -> None:
    payload = build_todo_payload({"order_id": "ord_2"})
    assert payload == {"title": "ord_2", "completed": False}


def test_submit_is_idempotent_on_platform_order_id() -> None:
    calls: list[tuple[str, str, dict | None]] = []

    def fake_request(target: Any, method: str, path: str, body: dict | None = None) -> Any:
        calls.append((method, path, body))
        if method == "GET" and path.startswith("/todos?title="):
            return [{"id": 99, "title": "ord_1"}]
        raise AssertionError(f"should not reach {method} {path} once an existing todo matches")

    adapter = JsonPlaceholderDemoAdapter()
    with patch.object(JsonPlaceholderDemoAdapter, "_request", side_effect=fake_request):
        result = adapter.submit(_TARGET, {"order_id": "ord_1", "erp_customer_id": "5"})

    assert result.success
    assert result.erp_order_id == "99"
    assert calls == [("GET", "/todos?title=ord_1", None)]


def test_submit_creates_a_todo_with_the_resolved_customer_id() -> None:
    created_body: dict[str, Any] = {}

    def fake_request(target: Any, method: str, path: str, body: dict | None = None) -> Any:
        if method == "GET":
            return []  # no existing todo for this order_id
        if method == "POST" and path == "/todos":
            created_body.update(body or {})
            return {"id": 201, **(body or {})}
        raise AssertionError(f"unexpected call: {method} {path}")

    adapter = JsonPlaceholderDemoAdapter()
    with patch.object(JsonPlaceholderDemoAdapter, "_request", side_effect=fake_request):
        result = adapter.submit(
            _TARGET,
            {
                "order_id": "ord_2",
                "erp_customer_id": "5",
                "parties": {"end_customer_name": "Acme Downstream"},
            },
        )

    assert result.success
    assert result.erp_order_id == "201"
    assert created_body == {
        "title": "ord_2",
        "completed": False,
        "name": "Acme Downstream",
        "userId": 5,
    }


def test_submit_fails_closed_without_an_erp_customer_id() -> None:
    def fake_request(target: Any, method: str, path: str, body: dict | None = None) -> Any:
        if method == "GET":
            return []
        raise AssertionError(f"must not proceed without a customer: {method} {path}")

    adapter = JsonPlaceholderDemoAdapter()
    with patch.object(JsonPlaceholderDemoAdapter, "_request", side_effect=fake_request):
        result = adapter.submit(_TARGET, {"order_id": "ord_3"})

    assert not result.success
    assert result.terminal


def test_submit_fails_closed_on_invalid_erp_customer_id() -> None:
    def fake_request(target: Any, method: str, path: str, body: dict | None = None) -> Any:
        if method == "GET":
            return []
        raise AssertionError(f"must not proceed with a bad customer id: {method} {path}")

    adapter = JsonPlaceholderDemoAdapter()
    with patch.object(JsonPlaceholderDemoAdapter, "_request", side_effect=fake_request):
        result = adapter.submit(
            _TARGET, {"order_id": "ord_4", "erp_customer_id": "not-a-number"}
        )

    assert not result.success
    assert result.terminal
    assert "not-a-number" in (result.error or "")


def test_fetch_status_maps_completed_true() -> None:
    adapter = JsonPlaceholderDemoAdapter()
    with patch.object(
        JsonPlaceholderDemoAdapter,
        "_request",
        return_value={"id": 1, "title": "ord_1", "completed": True, "userId": 5},
    ):
        fields = adapter.fetch_status(_TARGET, "1")

    assert fields == {"completed": "true"}


def test_fetch_status_maps_completed_false() -> None:
    adapter = JsonPlaceholderDemoAdapter()
    with patch.object(
        JsonPlaceholderDemoAdapter,
        "_request",
        return_value={"id": 1, "title": "ord_1", "completed": False, "userId": 5},
    ):
        fields = adapter.fetch_status(_TARGET, "1")

    assert fields == {"completed": "false"}


def test_fetch_status_returns_none_when_order_not_found() -> None:
    adapter = JsonPlaceholderDemoAdapter()
    with patch.object(JsonPlaceholderDemoAdapter, "_request", return_value={}):
        assert adapter.fetch_status(_TARGET, "999") is None


def test_fetch_partner_orders_has_no_adoptable_lines_yet() -> None:
    """TODO (account-specific) in `fetch_partner_orders`'s docstring: JSONPlaceholder's
    public `/todos` schema has no product_key/quantity fields at all, so even a row that
    comes back is never adopted — this locks that behavior in rather than letting it
    silently start inventing fake lines later."""
    adapter = JsonPlaceholderDemoAdapter()
    with patch.object(
        JsonPlaceholderDemoAdapter,
        "_request",
        return_value=[{"id": 1, "title": "ord_1", "completed": False, "userId": 5}],
    ):
        orders = adapter.fetch_partner_orders(_TARGET, "5")

    assert orders == []


def test_fetch_shipments_and_fetch_invoices_are_always_empty() -> None:
    adapter = JsonPlaceholderDemoAdapter()
    assert adapter.fetch_shipments(_TARGET, "1") == []
    assert adapter.fetch_invoices(_TARGET, "1") == []


def test_cancel_calls_delete_and_reports_success() -> None:
    calls: list[tuple[str, str]] = []

    def fake_request(target: Any, method: str, path: str, body: dict | None = None) -> Any:
        calls.append((method, path))
        return {}

    adapter = JsonPlaceholderDemoAdapter()
    with patch.object(JsonPlaceholderDemoAdapter, "_request", side_effect=fake_request):
        result = adapter.cancel(_TARGET, "1")

    assert result.success
    assert calls == [("DELETE", "/todos/1")]


def test_submit_is_terminal_on_a_4xx_and_retryable_on_a_5xx() -> None:
    from src.modules.integration.erp.infrastructure.jsonplaceholder_demo_adapter import (
        _JsonPlaceholderDemoError,
    )

    def fake_request_4xx(target: Any, method: str, path: str, body: dict | None = None) -> Any:
        if method == "GET":
            return []
        raise _JsonPlaceholderDemoError("HTTP 400", terminal=True)

    def fake_request_5xx(target: Any, method: str, path: str, body: dict | None = None) -> Any:
        if method == "GET":
            return []
        raise _JsonPlaceholderDemoError("HTTP 503", terminal=False)

    adapter = JsonPlaceholderDemoAdapter()
    with patch.object(JsonPlaceholderDemoAdapter, "_request", side_effect=fake_request_4xx):
        result = adapter.submit(_TARGET, {"order_id": "ord_5", "erp_customer_id": "5"})
    assert not result.success and result.terminal

    with patch.object(JsonPlaceholderDemoAdapter, "_request", side_effect=fake_request_5xx):
        result = adapter.submit(_TARGET, {"order_id": "ord_6", "erp_customer_id": "5"})
    assert not result.success and not result.terminal


@pytest.mark.parametrize(
    ("status_code", "expected_terminal"),
    [(400, True), (404, True), (500, False), (503, False)],
)
def test_request_classifies_http_errors_by_status_code(
    status_code: int, expected_terminal: bool
) -> None:
    import urllib.error

    from src.modules.integration.erp.infrastructure.jsonplaceholder_demo_adapter import (
        _JsonPlaceholderDemoError,
    )

    adapter = JsonPlaceholderDemoAdapter()
    http_error = urllib.error.HTTPError(
        "https://jsonplaceholder.typicode.com/todos/1", status_code, "err", {}, None
    )
    with patch("urllib.request.urlopen", side_effect=http_error):
        with pytest.raises(_JsonPlaceholderDemoError) as exc_info:
            adapter._request(_TARGET, "GET", "/todos/1")

    assert exc_info.value.terminal is expected_terminal
