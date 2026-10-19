"""End-to-end: the real NetSuiteAdapter driving the faithful in-process mock NetSuite over
real OAuth-1.0a-signed HTTP on a loopback ephemeral port.

Unlike the unit tests (which mock the HTTP seam), this exercises the whole stack the way a
live NetSuite would: TBA signing, the SuiteTalk REST URL shapes, the `204 + Location` create
contract, external-id idempotency, SuiteQL reads, and record transforms. The mock
*independently* re-verifies the OAuth signature, so a green run proves the adapter signs
correctly — not merely that it sends a header. Needs no Postgres or cloud services: pure stdlib +
loopback sockets, so it runs in the offline gate (no self-skip).

This is the "plug and play" proof: the only difference between this and a live NetSuite is
`base_url` + the resolved secret.
"""

from __future__ import annotations

import json
import threading
from http.server import ThreadingHTTPServer
from typing import TYPE_CHECKING

import pytest
from scripts.mock_netsuite import MockNetSuiteState, make_handler, seed_default
from src.modules.integration.erp.application.ports import ErpTarget
from src.modules.integration.erp.domain.status_mapping import CanonicalStatus, map_native_status
from src.modules.integration.erp.infrastructure.netsuite_adapter import NetSuiteAdapter

if TYPE_CHECKING:
    from collections.abc import Iterator

_CONSUMER_SECRET = "consumer-secret-value"
_TOKEN_SECRET = "token-secret-value"


@pytest.fixture
def mock_netsuite() -> Iterator[tuple[str, MockNetSuiteState]]:
    state = seed_default(MockNetSuiteState())
    handler = make_handler(state, consumer_secret=_CONSUMER_SECRET, token_secret=_TOKEN_SECRET)
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address
        yield f"http://{host}:{port}", state
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _target(base_url: str) -> ErpTarget:
    return ErpTarget(
        erp_type="NETSUITE",
        base_url=base_url,
        credentials={"account_id": "TSTDRV", "consumer_key": "ck", "token_id": "ti"},
        secret=json.dumps({"consumer_secret": _CONSUMER_SECRET, "token_secret": _TOKEN_SECRET}),
    )


def _order_payload() -> dict[str, object]:
    return {
        "order_id": "ord_e2e_1",
        "erp_customer_id": "101",  # seeded customer
        "lines": [
            {
                "product_key": "ANVIL",
                "quantity": 2,
                "unit_price": {"amount": "19.99", "currency": "USD"},
            },
            {"product_key": "SPRING", "quantity": 5},
        ],
    }


def test_submit_fetch_fulfill_invoice_cancel_end_to_end(
    mock_netsuite: tuple[str, MockNetSuiteState],
) -> None:
    base_url, state = mock_netsuite
    target = _target(base_url)
    adapter = NetSuiteAdapter(timeout_seconds=5.0)

    # 1. submit -> creates a real salesOrder in the mock, returns its internal id
    result = adapter.submit(target, _order_payload())
    assert result.success, result.error
    order_id = result.erp_order_id
    assert order_id is not None
    assert order_id in state.transactions

    # 2. idempotent re-submit returns the SAME order (found by externalId), no duplicate
    before = len(state.transactions)
    again = adapter.submit(target, _order_payload())
    assert again.success
    assert again.erp_order_id == order_id
    assert len(state.transactions) == before

    # 3. fetch_status reads NetSuite's status and maps to the canonical lifecycle
    fields = adapter.fetch_status(target, order_id)
    assert fields is not None
    assert map_native_status("NETSUITE", fields) is CanonicalStatus.CONFIRMED

    # 4. a NetSuite-side partial fulfillment + invoice, then the adapter reads them back
    state.add_fulfillment(order_id, [{"item_id": "201", "itemid": "ANVIL", "quantity": 2}])
    state.add_invoice(order_id, [{"item_id": "201", "itemid": "ANVIL", "quantity": 2}])

    shipments = adapter.fetch_shipments(target, order_id)
    assert len(shipments) == 1
    assert shipments[0].lines[0].product_key == "ANVIL"
    assert shipments[0].lines[0].quantity == "2"

    invoices = adapter.fetch_invoices(target, order_id)
    assert len(invoices) == 1
    assert invoices[0].lines[0].product_key == "ANVIL"

    # 5. partner-order discovery reads the order back for the customer
    partner_orders = adapter.fetch_partner_orders(target, "101")
    assert any(o.erp_order_id == order_id for o in partner_orders)

    # 6. cancel deletes the order; fetch_status then reports it gone
    cancelled = adapter.cancel(target, order_id)
    assert cancelled.success
    assert adapter.fetch_status(target, order_id) is None


def test_a_bad_signature_is_rejected(mock_netsuite: tuple[str, MockNetSuiteState]) -> None:
    """Proves the mock really verifies TBA signatures: a wrong token secret -> auth fails,
    so submit fails terminally rather than silently succeeding."""
    base_url, _ = mock_netsuite
    target = ErpTarget(
        erp_type="NETSUITE",
        base_url=base_url,
        credentials={"account_id": "TSTDRV", "consumer_key": "ck", "token_id": "ti"},
        secret=json.dumps({"consumer_secret": _CONSUMER_SECRET, "token_secret": "WRONG"}),
    )
    result = NetSuiteAdapter(timeout_seconds=5.0).submit(target, _order_payload())
    assert not result.success
    assert result.terminal
