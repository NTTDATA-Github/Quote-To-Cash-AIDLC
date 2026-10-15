"""Dev-only mock NetSuite — a faithful SuiteTalk REST Web Services stand-in. NOT shipped.

Stands in for a real NetSuite account so the `NetSuiteAdapter`
(`src/modules/integration/erp/infrastructure/netsuite_adapter.py`) can be run and tested
end-to-end — the real OAuth 1.0a signing, the real HTTP shaping, SuiteQL reads and record
transforms — without a live account. Switching the platform to a real NetSuite is then a
config-only change (`ErpConnection.base_url` + the secret), because the adapter never knows
it was talking to this mock. Nothing in `src/` imports this; it's a manual/testing aid, same
convention as `scripts/dev_webhook_receiver.py`. Stdlib only, on purpose.

Fidelity: implements exactly the SuiteTalk REST surface the adapter calls —
  * `GET  /services/rest/record/v1/salesOrder/{id}`           (read a sales order)
  * `GET  /services/rest/record/v1/salesOrder/eid:{externalId}` (external-id lookup, idempotency)
  * `POST /services/rest/record/v1/salesOrder`                 (create; 204 + Location header)
  * `DELETE /services/rest/record/v1/salesOrder/{id}`          (cancel)
  * `POST /services/rest/record/v1/salesOrder/{id}/!transform/{itemFulfillment|invoice}`
  * `POST /services/rest/query/v1/suiteql`                     (the SELECTs the adapter sends)
When configured with the four TBA credentials it **independently re-verifies the OAuth 1.0a
HMAC-SHA256 signature** on every request (a bad signature → 401), so the mock is a real
conformance check of the adapter's signing, not just a presence check. The verification is
deliberately re-implemented here rather than imported from the adapter, so a bug in the
adapter's signing can't hide behind the same bug in the mock.

Usage:
    python -m scripts.mock_netsuite --port 8075 \\
        --account-id TSTDRV123 --consumer-key ck --token-id ti \\
        --consumer-secret cs --token-secret ts
Omit the credentials to accept any well-formed `Authorization: OAuth ...` header unverified.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

_RECORD_PREFIX = "/services/rest/record/v1/salesOrder"
_SUITEQL_PATH = "/services/rest/query/v1/suiteql"
_DEFAULT_WEBHOOK_URL = "http://127.0.0.1:8000/erp/webhook/conn_netsuite"
_DEFAULT_WEBHOOK_SECRET = "ns-webhook-demo"


@dataclass
class _Transaction:
    internal_id: str
    record_type: str  # SalesOrd | ItemShip | CustInvc
    tranid: str
    lines: list[dict[str, Any]]  # [{"item_id","itemid","quantity","rate"}]
    external_id: str = ""
    entity: str = ""
    created_from: str = ""
    subsidiary: str = ""
    status: str = "Pending Fulfillment"
    order_status: str = "_pendingFulfillment"


@dataclass
class MockNetSuiteState:
    """In-memory NetSuite. `items` maps a SKU (itemid) to its internal id; `customers` is
    the set of valid customer internal ids. Transactions (sales orders, fulfillments,
    invoices) are keyed by internal id."""

    items: dict[str, str] = field(default_factory=dict)
    customers: set[str] = field(default_factory=set)
    transactions: dict[str, _Transaction] = field(default_factory=dict)
    _seq: int = 1000

    def next_id(self) -> str:
        self._seq += 1
        return str(self._seq)

    def item_itemid(self, internal_id: str) -> str:
        for itemid, iid in self.items.items():
            if iid == internal_id:
                return itemid
        return ""

    def find_by_external_id(self, external_id: str) -> _Transaction | None:
        for txn in self.transactions.values():
            if txn.record_type == "SalesOrd" and txn.external_id == external_id:
                return txn
        return None

    def _lines_from_body(self, body: dict[str, Any], fallback: list[dict[str, Any]]):
        """Build transaction lines from a request body's `item.items`, falling back to a
        source order's lines (used by transforms that don't restate every line)."""
        raw = ((body.get("item") or {}).get("items")) if body else None
        if not raw:
            return [dict(line) for line in fallback]
        lines: list[dict[str, Any]] = []
        for entry in raw:
            item_ref = entry.get("item") or {}
            item_id = str(item_ref.get("id") or "")
            lines.append(
                {
                    "item_id": item_id,
                    "itemid": self.item_itemid(item_id),
                    "quantity": entry.get("quantity", 1),
                    "rate": entry.get("rate"),
                }
            )
        return lines

    # --- NetSuite-side events the test (or a human) can trigger directly ---
    def add_fulfillment(self, sales_order_id: str, lines: list[dict[str, Any]] | None = None):
        source = self.transactions[sales_order_id]
        txn = _Transaction(
            internal_id=self.next_id(),
            record_type="ItemShip",
            tranid=f"IF{self._seq}",
            lines=lines or [dict(line) for line in source.lines],
            created_from=sales_order_id,
        )
        self.transactions[txn.internal_id] = txn
        return txn

    def add_invoice(self, sales_order_id: str, lines: list[dict[str, Any]] | None = None):
        source = self.transactions[sales_order_id]
        txn = _Transaction(
            internal_id=self.next_id(),
            record_type="CustInvc",
            tranid=f"INV{self._seq}",
            lines=lines or [dict(line) for line in source.lines],
            created_from=sales_order_id,
        )
        self.transactions[txn.internal_id] = txn
        return txn

    def set_status(self, sales_order_id: str, status: str, order_status: str) -> None:
        txn = self.transactions[sales_order_id]
        txn.status = status
        txn.order_status = order_status

    def add_sales_order(
        self,
        *,
        entity: str,
        subsidiary: str,
        lines: list[dict[str, Any]],
        external_id: str = "",
    ) -> _Transaction:
        internal_id = self.next_id()
        txn = _Transaction(
            internal_id=internal_id,
            record_type="SalesOrd",
            tranid=f"SO{self._seq}",
            lines=lines,
            external_id=external_id,
            entity=entity,
            subsidiary=subsidiary,
        )
        self.transactions[internal_id] = txn
        return txn


def seed_default(state: MockNetSuiteState) -> MockNetSuiteState:
    """A small catalog + one customer, plus two existing sales orders for that customer so
    the platform's discovery/reconcile path has NetSuite orders to adopt (mirrors how the
    Odoo demo reads orders already present in Odoo). Enough for the integration test and a
    manual demo; the integration test only relies on the items/customer."""
    state.items.update({"ANVIL": "201", "SPRING": "202", "GEAR": "203"})
    state.customers.update({"101"})
    # Existing sales orders for customer 101, subsidiary "NS1" (matches the seeded
    # subsidiary_route). Lines carry item internal id + SKU + quantity + rate.
    if not any(t.record_type == "SalesOrd" for t in state.transactions.values()):
        state.add_sales_order(
            entity="101",
            subsidiary="NS1",
            external_id="PO-10492",
            lines=[
                {"item_id": "201", "itemid": "ANVIL", "quantity": 2, "rate": 19.99},
                {"item_id": "202", "itemid": "SPRING", "quantity": 5, "rate": 4.50},
            ],
        )
        state.add_sales_order(
            entity="101",
            subsidiary="NS1",
            external_id="PO-10493",
            lines=[{"item_id": "203", "itemid": "GEAR", "quantity": 1, "rate": 99.00}],
        )
    return state


# --- OAuth 1.0a verification (independent re-implementation; see module docstring) ---
def _pct(value: str) -> str:
    return urllib.parse.quote(str(value), safe="")


def _verify_signature(
    method: str,
    url: str,
    auth_header: str,
    *,
    consumer_secret: str,
    token_secret: str,
) -> bool:
    params = dict(re.findall(r'(\w+)="([^"]*)"', auth_header))
    provided = urllib.parse.unquote(params.get("oauth_signature", ""))
    if not provided:
        return False
    split = urllib.parse.urlsplit(url)
    base_url = urllib.parse.urlunsplit((split.scheme, split.netloc, split.path, "", ""))
    signed = {k: v for k, v in params.items() if k.startswith("oauth_") and k != "oauth_signature"}
    all_params = [(k, urllib.parse.unquote(v)) for k, v in signed.items()]
    all_params += urllib.parse.parse_qsl(split.query)
    normalized = "&".join(f"{_pct(k)}={_pct(v)}" for k, v in sorted(all_params))
    base_string = f"{method.upper()}&{_pct(base_url)}&{_pct(normalized)}"
    signing_key = f"{_pct(consumer_secret)}&{_pct(token_secret)}"
    expected = base64.b64encode(
        hmac.new(signing_key.encode("utf-8"), base_string.encode("utf-8"), hashlib.sha256).digest()
    ).decode("ascii")
    return hmac.compare_digest(expected, provided)


def _suiteql_rows(state: MockNetSuiteState, query: str) -> list[dict[str, Any]]:
    """Recognize exactly the SELECTs the adapter sends; anything else returns no rows."""
    q = " ".join(query.split())
    item_match = re.search(r"FROM item WHERE itemid = '([^']*)'", q)
    if item_match:
        internal = state.items.get(item_match.group(1))
        return [{"id": internal}] if internal else []
    if "FROM unitstypeuom" in q or "FROM salestaxitem" in q:
        return []  # graceful-degradation lookups — unseeded by default
    entity_match = re.search(r"type = 'SalesOrd' AND entity = (\d+)", q)
    if entity_match:
        entity = entity_match.group(1)
        return [
            {
                "id": t.internal_id,
                "tranid": t.tranid,
                "externalid": t.external_id,
                "subsidiary": t.subsidiary,
            }
            for t in state.transactions.values()
            if t.record_type == "SalesOrd" and t.entity == entity
        ]
    ship_match = re.search(r"type = 'ItemShip' AND createdfrom = (\d+)", q)
    if ship_match:
        return _created_from_rows(state, "ItemShip", ship_match.group(1))
    invoice_match = re.search(r"type = 'CustInvc' AND createdfrom = (\d+)", q)
    if invoice_match:
        return _created_from_rows(state, "CustInvc", invoice_match.group(1))
    line_match = re.search(r"tl\.transaction = (\d+)", q)
    if line_match:
        txn = state.transactions.get(line_match.group(1))
        if txn is None:
            return []
        return [
            {
                "itemid": line.get("itemid"),
                "quantity": line.get("quantity"),
                "rate": line.get("rate"),
            }
            for line in txn.lines
            if line.get("itemid")
        ]
    return []


def _created_from_rows(
    state: MockNetSuiteState, record_type: str, created_from: str
) -> list[dict[str, Any]]:
    return [
        {"id": t.internal_id, "tranid": t.tranid}
        for t in state.transactions.values()
        if t.record_type == record_type and t.created_from == created_from
    ]


def _salesorder_json(txn: _Transaction) -> dict[str, Any]:
    return {
        "id": txn.internal_id,
        "externalId": txn.external_id,
        "tranId": txn.tranid,
        "entity": {"id": txn.entity},
        "status": txn.status,
        "orderStatus": txn.order_status,
        "item": {
            "items": [
                {"item": {"id": line.get("item_id")}, "quantity": line.get("quantity")}
                for line in txn.lines
            ]
        },
    }


def push_webhook(url: str, secret: str, erp_order_id: str, status: str) -> None:
    """POST the same HMAC webhook a SuiteScript user-event would send. The body is an id
    plus the sales-order status; shipment and invoice lines are read back by the platform."""
    body = json.dumps(
        {
            "erp_type": "NETSUITE",
            "erp_order_id": erp_order_id,
            "status": status,
            "event_id": f"{erp_order_id}-{status}-{time.time_ns()}",
        }
    ).encode("utf-8")
    signature = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    request = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json", "x-erp-signature": signature},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            print(
                f"webhook {erp_order_id} {status} -> {response.status}",
                flush=True,
            )
    except urllib.error.HTTPError as exc:
        print(f"webhook {erp_order_id} {status} -> {exc.code} {exc.read()[:200]!r}", flush=True)
    except urllib.error.URLError as exc:
        print(f"webhook {erp_order_id} {status} failed: {exc.reason}", flush=True)


def _openapi() -> dict[str, Any]:
    order_param = {
        "name": "id",
        "in": "path",
        "required": True,
        "schema": {"type": "string"},
        "description": "Sales order internal id already in AdminOps, such as 1001 or 1002.",
    }

    def post(summary: str, description: str) -> dict[str, Any]:
        return {
            "post": {
                "summary": summary,
                "description": description,
                "parameters": [order_param],
                "responses": {"204": {"description": "State changed and webhook posted"}},
            }
        }

    return {
        "openapi": "3.0.3",
        "info": {
            "title": "NetSuite mock",
            "version": "1",
            "description": (
                "Triggers a SuiteScript-style webhook to the platform. "
                "Use an order already in AdminOps (1001 PO-10492, 1002 PO-10493). "
                "Notifications show up within a few seconds under Notifications. "
                "Create is adopted on the next poll, about 30 seconds, because a webhook "
                "cannot adopt an order the platform has not seen yet."
            ),
        },
        "paths": {
            "/demo/sales-orders": {
                "get": {
                    "summary": "List sales orders",
                    "responses": {"200": {"description": "Current sales orders"}},
                },
                "post": {
                    "summary": "Create a sales order for customer 101",
                    "description": (
                        "Subsidiary NS1, item 201 (ANVIL), quantity 1, status Pending Fulfillment."
                    ),
                    "requestBody": {
                        "required": False,
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "externalId": {"type": "string"},
                                        "itemId": {"type": "string", "default": "201"},
                                        "quantity": {"type": "number", "default": 1},
                                    },
                                }
                            }
                        },
                    },
                    "responses": {"201": {"description": "Created. Adopted on the next poll."}},
                },
            },
            "/demo/sales-orders/{id}/fulfill": post(
                "Fulfill",
                "Item fulfillment. Reseller notification: ShipmentRecorded.",
            ),
            "/demo/sales-orders/{id}/invoice": post(
                "Invoice",
                "Customer invoice. Reseller notification: InvoiceRecorded."
                " The order stays Confirmed.",
            ),
            "/demo/sales-orders/{id}/bill": post(
                "Bill",
                "Marks the sales order Billed. Reseller notification: OrderClosed.",
            ),
            "/demo/sales-orders/{id}/cancel": post(
                "Cancel",
                "Marks the sales order Cancelled. Reseller notification: OrderCancelled.",
            ),
        },
    }


_DOCS_HTML = """<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>NetSuite mock</title>
  <link rel="stylesheet" href="https://unpkg.com/swagger-ui-dist@5/swagger-ui.css">
</head>
<body>
<div id="ui"></div>
<script src="https://unpkg.com/swagger-ui-dist@5/swagger-ui-bundle.js"></script>
<script>
SwaggerUIBundle({ url: "/openapi.json", dom_id: "#ui" });
</script>
</body>
</html>
"""


def make_handler(
    state: MockNetSuiteState,
    *,
    consumer_secret: str | None = None,
    token_secret: str | None = None,
    webhook_url: str = _DEFAULT_WEBHOOK_URL,
    webhook_secret: str = _DEFAULT_WEBHOOK_SECRET,
) -> type[BaseHTTPRequestHandler]:
    verify = consumer_secret is not None and token_secret is not None

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args: object) -> None:  # silence default access log
            pass

        # --- helpers ---
        def _authorized(self) -> bool:
            auth = self.headers.get("Authorization", "")
            if not auth.startswith("OAuth "):
                return False
            if not verify:
                return True
            host = self.headers.get("Host", "")
            url = f"http://{host}{self.path}"
            assert consumer_secret is not None and token_secret is not None
            return _verify_signature(
                self.command,
                url,
                auth,
                consumer_secret=consumer_secret,
                token_secret=token_secret,
            )

        def _body(self) -> dict[str, Any]:
            length = int(self.headers.get("Content-Length", "0"))
            if not length:
                return {}
            try:
                return json.loads(self.rfile.read(length))
            except json.JSONDecodeError:
                return {}

        def _send_json(self, status: int, payload: dict[str, Any]) -> None:
            data = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _send_empty(self, status: int, location: str | None = None) -> None:
            self.send_response(status)
            if location:
                self.send_header("Location", location)
            self.send_header("Content-Length", "0")
            self.end_headers()

        def _not_found(self) -> None:
            self._send_json(404, {"title": "Record not found", "o:errorCode": "RCRD_DSNT_EXIST"})

        def _unauthorized(self) -> None:
            self._send_json(
                401, {"title": "Invalid login attempt.", "o:errorCode": "INVALID_LOGIN"}
            )

        def _notify(self, erp_order_id: str, status: str) -> None:
            if webhook_url and webhook_secret:
                push_webhook(webhook_url, webhook_secret, erp_order_id, status)

        def _demo(self) -> bool:
            path = urllib.parse.urlsplit(self.path).path.rstrip("/") or "/"
            if path == "/docs":
                data = _DOCS_HTML.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                return True
            if path == "/openapi.json":
                self._send_json(200, _openapi())
                return True
            if not path.startswith("/demo/"):
                return False
            if path == "/demo/sales-orders" and self.command == "GET":
                orders = [
                    {
                        "id": txn.internal_id,
                        "tranId": txn.tranid,
                        "externalId": txn.external_id,
                        "status": txn.status,
                        "entity": txn.entity,
                    }
                    for txn in state.transactions.values()
                    if txn.record_type == "SalesOrd"
                ]
                self._send_json(200, {"orders": orders})
                return True
            if path == "/demo/sales-orders" and self.command == "POST":
                body = self._body()
                item_id = str(body.get("itemId") or "201")
                itemid = state.item_itemid(item_id)
                if not itemid:
                    self._send_json(400, {"title": f"Unknown item {item_id}"})
                    return True
                txn = state.add_sales_order(
                    entity="101",
                    subsidiary="NS1",
                    external_id=str(body.get("externalId") or ""),
                    lines=[
                        {
                            "item_id": item_id,
                            "itemid": itemid,
                            "quantity": body.get("quantity") or 1,
                            "rate": 19.99,
                        }
                    ],
                )
                self._notify(txn.internal_id, txn.status)
                self._send_json(
                    201, {"id": txn.internal_id, "tranId": txn.tranid, "status": txn.status}
                )
                return True
            action = re.match(r"^/demo/sales-orders/([^/]+)/(fulfill|invoice|bill|cancel)$", path)
            if action is None or self.command != "POST":
                self._not_found()
                return True
            order_id, name = action.group(1), action.group(2)
            source = state.transactions.get(order_id)
            if source is None or source.record_type != "SalesOrd":
                self._not_found()
                return True
            if name == "fulfill":
                state.add_fulfillment(order_id)
            elif name == "invoice":
                state.add_invoice(order_id)
            elif name == "bill":
                state.set_status(order_id, "Billed", "_fullyBilled")
            else:
                state.set_status(order_id, "Cancelled", "_cancelled")
            self._notify(order_id, state.transactions[order_id].status)
            self._send_empty(204)
            return True

        # --- routes ---
        def do_GET(self) -> None:
            if self._demo():
                return None
            if not self._authorized():
                return self._unauthorized()
            path = urllib.parse.urlsplit(self.path).path
            if path.startswith(_RECORD_PREFIX + "/"):
                identifier = path[len(_RECORD_PREFIX) + 1 :]
                txn = self._resolve_salesorder(identifier)
                if txn is None:
                    return self._not_found()
                return self._send_json(200, _salesorder_json(txn))
            return self._not_found()

        def do_DELETE(self) -> None:
            if not self._authorized():
                return self._unauthorized()
            path = urllib.parse.urlsplit(self.path).path
            if path.startswith(_RECORD_PREFIX + "/"):
                identifier = path[len(_RECORD_PREFIX) + 1 :]
                txn = self._resolve_salesorder(identifier)
                if txn is None:
                    return self._not_found()
                order_id = txn.internal_id
                del state.transactions[order_id]
                self._notify(order_id, "Cancelled")
                return self._send_empty(204)
            return self._not_found()

        def do_POST(self) -> None:
            if self._demo():
                return None
            if not self._authorized():
                return self._unauthorized()
            path = urllib.parse.urlsplit(self.path).path
            body = self._body()
            if path == _SUITEQL_PATH:
                rows = _suiteql_rows(state, str(body.get("q", "")))
                return self._send_json(200, {"items": rows, "count": len(rows), "hasMore": False})
            transform = re.match(
                rf"^{re.escape(_RECORD_PREFIX)}/(\d+)/!transform/(itemFulfillment|invoice)$", path
            )
            if transform:
                return self._handle_transform(transform.group(1), transform.group(2), body)
            if path == _RECORD_PREFIX:
                return self._handle_create(body)
            return self._not_found()

        # --- route implementations ---
        def _resolve_salesorder(self, identifier: str) -> _Transaction | None:
            if identifier.startswith("eid:"):
                return state.find_by_external_id(identifier[4:])
            txn = state.transactions.get(identifier)
            return txn if txn and txn.record_type == "SalesOrd" else None

        def _handle_create(self, body: dict[str, Any]) -> None:
            entity_id = str((body.get("entity") or {}).get("id") or "")
            if entity_id not in state.customers:
                return self._send_json(
                    400,
                    {
                        "title": f"Invalid customer reference {entity_id!r}",
                        "o:errorCode": "INVALID_KEY_OR_REF",
                    },
                )
            lines: list[dict[str, Any]] = []
            for entry in (body.get("item") or {}).get("items") or []:
                item_id = str((entry.get("item") or {}).get("id") or "")
                itemid = state.item_itemid(item_id)
                if not itemid:
                    return self._send_json(
                        400,
                        {
                            "title": f"Invalid item reference {item_id!r}",
                            "o:errorCode": "INVALID_KEY_OR_REF",
                        },
                    )
                lines.append(
                    {
                        "item_id": item_id,
                        "itemid": itemid,
                        "quantity": entry.get("quantity", 1),
                        "rate": entry.get("rate"),
                    }
                )
            internal_id = state.next_id()
            txn = _Transaction(
                internal_id=internal_id,
                record_type="SalesOrd",
                tranid=f"SO{state._seq}",
                lines=lines,
                external_id=str(body.get("externalId") or ""),
                entity=entity_id,
                subsidiary=str((body.get("subsidiary") or {}).get("id") or "NS1"),
            )
            state.transactions[internal_id] = txn
            self._notify(internal_id, txn.status)
            self._send_empty(204, location=f"{_RECORD_PREFIX}/{internal_id}")

        def _handle_transform(self, source_id: str, target: str, body: dict[str, Any]) -> None:
            source = state.transactions.get(source_id)
            if source is None or source.record_type != "SalesOrd":
                return self._not_found()
            lines = state._lines_from_body(body, source.lines)
            if target == "itemFulfillment":
                txn = state.add_fulfillment(source_id, lines)
            else:
                txn = state.add_invoice(source_id, lines)
            self._notify(source_id, source.status)
            self._send_empty(
                204, location=f"{_RECORD_PREFIX.rsplit('/', 1)[0]}/{target}/{txn.internal_id}"
            )

    return Handler


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--port", type=int, default=8075)
    parser.add_argument("--account-id", default="MOCK_ACCT")
    parser.add_argument("--consumer-key", default=None)
    parser.add_argument("--token-id", default=None)
    parser.add_argument("--consumer-secret", default=None)
    parser.add_argument("--token-secret", default=None)
    parser.add_argument("--webhook-url", default=_DEFAULT_WEBHOOK_URL)
    parser.add_argument("--webhook-secret", default=_DEFAULT_WEBHOOK_SECRET)
    args = parser.parse_args()

    state = seed_default(MockNetSuiteState())
    handler = make_handler(
        state,
        consumer_secret=args.consumer_secret,
        token_secret=args.token_secret,
        webhook_url=args.webhook_url,
        webhook_secret=args.webhook_secret,
    )
    server = ThreadingHTTPServer(("127.0.0.1", args.port), handler)
    print(f"NetSuite SuiteTalk REST service listening on http://127.0.0.1:{args.port}", flush=True)
    print(f"Swagger UI http://127.0.0.1:{args.port}/docs", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()


if __name__ == "__main__":
    main()
