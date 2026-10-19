"""Dev-only mock SAP S/4HANA — a minimal OData stand-in for the Sales Order API
(`API_SALES_ORDER_SRV`). NOT shipped.

Lets a SAP connection be registered with a real, reachable `base_url` so the existing
generic onboarding pipeline (`GenericErpProbe` + Basic auth + the LLM's own path-guessing
in `LlmSampleRequestSuggester`) actually runs live for SAP, the same way it does for any
other ERP — no SAP-specific code in `MappingService`. Field names on the returned records
are the real ones from SAP's published `API_SALES_ORDER_SRV` spec (A_SalesOrder /
A_SalesOrderItem), so the data looks like SAP even though the server doesn't. Stdlib
only, same convention as `scripts/mock_netsuite.py`.

Two endpoint families:
  * The OData read path — what "Suggest & pull" actually fetches:
      GET /sap/opu/odata/sap/API_SALES_ORDER_SRV/A_SalesOrder
      GET /sap/opu/odata/sap/API_SALES_ORDER_SRV/A_SalesOrderItem
    Both require `Authorization: Basic ...` (verified against --username/--password if
    given; any well-formed Basic header is accepted otherwise).
  * A separate `/demo` path, unauthenticated, for manually driving the 10 seeded sample
    orders through their lifecycle from Swagger UI (`/docs`) while testing — each action
    pushes the same kind of webhook `mock_netsuite.py` does.

Usage:
    python -m scripts.mock_sap --port 8076 --username demo --password demo
Omit --username/--password to accept any Basic header unverified.
"""

from __future__ import annotations

import argparse
import base64
import json
import re
import urllib.parse
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from scripts.mock_netsuite import push_webhook

_DEMO_PREFIX = "/demo/sales-orders"
_ODATA_ORDER = "/sap/opu/odata/sap/API_SALES_ORDER_SRV/A_SalesOrder"
_ODATA_ITEM = "/sap/opu/odata/sap/API_SALES_ORDER_SRV/A_SalesOrderItem"
_DEFAULT_WEBHOOK_URL = "http://127.0.0.1:8000/erp/webhook/conn_sap"
_DEFAULT_WEBHOOK_SECRET = "sap-webhook-demo"

# Lifecycle this mock lets you drive, and the SAP `OverallSDProcessStatus` code each
# maps to (A = open, B = being processed, C = completely processed).
_STATUS_CODE = {
    "OPEN": "A",
    "IN_PROCESS": "B",
    "DELIVERED": "B",
    "INVOICED": "B",
    "COMPLETED": "C",
    "CANCELLED": "C",
}
# action -> (status it produces, status(es) it's valid from)
_TRANSITIONS = {
    "confirm": ("IN_PROCESS", {"OPEN"}),
    "deliver": ("DELIVERED", {"IN_PROCESS"}),
    "invoice": ("INVOICED", {"DELIVERED"}),
    "complete": ("COMPLETED", {"INVOICED"}),
    "cancel": ("CANCELLED", {"OPEN", "IN_PROCESS", "DELIVERED", "INVOICED"}),
}


@dataclass
class _SalesOrder:
    sales_order: str  # e.g. "0000090001"
    sold_to_party: str
    net_amount: str
    status: str  # key into _STATUS_CODE
    items: list[dict[str, Any]]  # [{"item": "10", "material": "...", "quantity": "2"}]


@dataclass
class MockSapState:
    orders: dict[str, _SalesOrder] = field(default_factory=dict)


def seed_default() -> MockSapState:
    """10 sample sales orders spanning every stage of the lifecycle, so there's always
    at least one order sitting in each status to demo from — not just 10 identical
    "Open" rows. Field names/shape are real A_SalesOrder / A_SalesOrderItem fields."""
    statuses = [
        "OPEN",
        "OPEN",
        "OPEN",
        "IN_PROCESS",
        "IN_PROCESS",
        "DELIVERED",
        "DELIVERED",
        "INVOICED",
        "COMPLETED",
        "CANCELLED",
    ]
    materials = ["MAT-ANVIL", "MAT-SPRING", "MAT-GEAR"]
    orders: dict[str, _SalesOrder] = {}
    for i, status in enumerate(statuses, start=1):
        order_id = f"{90000 + i:010d}"
        orders[order_id] = _SalesOrder(
            sales_order=order_id,
            sold_to_party="0001000001",
            net_amount=str(100 * i + 19.99),
            status=status,
            items=[
                {
                    "sales_order": order_id,
                    "item": "10",
                    "material": materials[i % len(materials)],
                    "quantity": str(1 + i % 3),
                }
            ],
        )
    return MockSapState(orders=orders)


def _order_odata(order: _SalesOrder) -> dict[str, Any]:
    return {
        "SalesOrder": order.sales_order,
        "SalesOrderType": "OR",
        "SalesOrganization": "1710",
        "SoldToParty": order.sold_to_party,
        "TotalNetAmount": order.net_amount,
        "TransactionCurrency": "USD",
        "OverallSDProcessStatus": _STATUS_CODE[order.status],
        "CreationDate": "2026-01-01",
    }


def _item_odata(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "SalesOrder": item["sales_order"],
        "SalesOrderItem": item["item"],
        "Material": item["material"],
        "RequestedQuantity": item["quantity"],
        "NetAmount": item["quantity"],
    }


def _openapi() -> dict[str, Any]:
    id_param = {
        "name": "id",
        "in": "path",
        "required": True,
        "schema": {"type": "string"},
        "description": "A seeded sales order id, e.g. 0000090001 .. 0000090010.",
    }

    def action(summary: str, produces: str, valid_from: set[str]) -> dict[str, Any]:
        return {
            "post": {
                "summary": summary,
                "description": f"Valid from {sorted(valid_from)} -> {produces}. Pushes a webhook.",
                "parameters": [id_param],
                "responses": {
                    "200": {"description": "Status changed and webhook pushed"},
                    "409": {"description": "Order isn't in a status this action allows"},
                },
            }
        }

    return {
        "openapi": "3.0.3",
        "info": {
            "title": "SAP mock",
            "version": "1",
            "description": (
                "10 seeded sales orders (0000090001 .. 0000090010) across every lifecycle "
                "stage. The OData paths are what 'Suggest & pull' fetches for mapping; the "
                "/demo/sales-orders actions below are for manually triggering status-change "
                "events while testing — list them first to see each order's current status."
            ),
        },
        "paths": {
            _ODATA_ORDER: {
                "get": {
                    "summary": "OData: list A_SalesOrder (requires Basic auth)",
                    "responses": {"200": {"description": "Sales orders"}},
                }
            },
            _ODATA_ITEM: {
                "get": {
                    "summary": "OData: list A_SalesOrderItem (requires Basic auth)",
                    "responses": {"200": {"description": "Sales order line items"}},
                }
            },
            _DEMO_PREFIX: {
                "get": {
                    "summary": "List the 10 seeded sample orders with their current status",
                    "responses": {"200": {"description": "Current sales orders"}},
                }
            },
            f"{_DEMO_PREFIX}/{{id}}/confirm": action(
                "Confirm (-> IN_PROCESS)", "IN_PROCESS", {"OPEN"}
            ),
            f"{_DEMO_PREFIX}/{{id}}/deliver": action(
                "Deliver (-> DELIVERED)", "DELIVERED", {"IN_PROCESS"}
            ),
            f"{_DEMO_PREFIX}/{{id}}/invoice": action(
                "Invoice (-> INVOICED)", "INVOICED", {"DELIVERED"}
            ),
            f"{_DEMO_PREFIX}/{{id}}/complete": action(
                "Complete (-> COMPLETED)", "COMPLETED", {"INVOICED"}
            ),
            f"{_DEMO_PREFIX}/{{id}}/cancel": action(
                "Cancel (-> CANCELLED)",
                "CANCELLED",
                {"OPEN", "IN_PROCESS", "DELIVERED", "INVOICED"},
            ),
        },
    }


_DOCS_HTML = """<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>SAP mock</title>
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
    state: MockSapState,
    *,
    username: str | None = None,
    password: str | None = None,
    webhook_url: str = _DEFAULT_WEBHOOK_URL,
    webhook_secret: str = _DEFAULT_WEBHOOK_SECRET,
) -> type[BaseHTTPRequestHandler]:
    verify = username is not None and password is not None
    expected = None
    if verify:
        expected = base64.b64encode(f"{username}:{password}".encode()).decode()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args: object) -> None:  # silence default access log
            pass

        def _authorized(self) -> bool:
            auth = self.headers.get("Authorization", "")
            if not auth.startswith("Basic "):
                return False
            return not verify or auth[len("Basic ") :] == expected

        def _send_json(self, status: int, payload: Any) -> None:
            data = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _unauthorized(self) -> None:
            self._send_json(401, {"error": {"message": {"value": "Basic auth required"}}})

        def _not_found(self) -> None:
            self._send_json(404, {"error": {"message": {"value": "not found"}}})

        def _notify(self, order_id: str, status: str) -> None:
            if webhook_url and webhook_secret:
                push_webhook(webhook_url, webhook_secret, order_id, status, erp_type="SAP")

        def _docs(self) -> bool:
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
            return False

        def _demo_list(self) -> None:
            orders = [
                {
                    "id": o.sales_order,
                    "status": o.status,
                    "soldToParty": o.sold_to_party,
                    "netAmount": o.net_amount,
                }
                for o in sorted(state.orders.values(), key=lambda o: o.sales_order)
            ]
            self._send_json(200, {"orders": orders})

        def _demo_action(self, order_id: str, action_name: str) -> None:
            order = state.orders.get(order_id)
            if order is None:
                return self._not_found()
            transition = _TRANSITIONS.get(action_name)
            if transition is None:
                return self._not_found()
            next_status, valid_from = transition
            if order.status not in valid_from:
                allowed = sorted(valid_from)
                return self._send_json(
                    409, {"error": f"order {order_id} is {order.status}, not one of {allowed}"}
                )
            order.status = next_status
            self._notify(order_id, next_status)
            self._send_json(200, {"id": order_id, "status": next_status})

        def do_GET(self) -> None:
            if self._docs():
                return None
            path = urllib.parse.urlsplit(self.path).path
            if path == _DEMO_PREFIX:
                return self._demo_list()
            if path in (_ODATA_ORDER, _ODATA_ITEM):
                if not self._authorized():
                    return self._unauthorized()
                orders = sorted(state.orders.values(), key=lambda o: o.sales_order)
                if path == _ODATA_ORDER:
                    results = [_order_odata(o) for o in orders]
                else:
                    results = [_item_odata(item) for o in orders for item in o.items]
                return self._send_json(200, {"d": {"results": results}})
            return self._not_found()

        def do_POST(self) -> None:
            path = urllib.parse.urlsplit(self.path).path
            match = re.match(rf"^{re.escape(_DEMO_PREFIX)}/([^/]+)/([a-z]+)$", path)
            if match is None:
                return self._not_found()
            return self._demo_action(match.group(1), match.group(2))

    return Handler


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--port", type=int, default=8076)
    parser.add_argument("--username", default=None)
    parser.add_argument("--password", default=None)
    parser.add_argument("--webhook-url", default=_DEFAULT_WEBHOOK_URL)
    parser.add_argument("--webhook-secret", default=_DEFAULT_WEBHOOK_SECRET)
    args = parser.parse_args()

    state = seed_default()
    handler = make_handler(
        state,
        username=args.username,
        password=args.password,
        webhook_url=args.webhook_url,
        webhook_secret=args.webhook_secret,
    )
    server = ThreadingHTTPServer(("0.0.0.0", args.port), handler)
    print(f"SAP OData mock listening on http://0.0.0.0:{args.port}", flush=True)
    print(f"Swagger UI http://127.0.0.1:{args.port}/docs", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()


if __name__ == "__main__":
    main()
