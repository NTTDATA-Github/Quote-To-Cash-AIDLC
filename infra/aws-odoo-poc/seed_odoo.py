"""Seed the POC Odoo with realistic demo data (idempotent). Odoo-only subset of
scripts/seed_demo.py -- this POC has no portal Postgres/api/worker to seed.

Usage:
    ODOO_URL=http://<poc-ip>:8069 python3 seed_odoo.py
"""

from __future__ import annotations

import json
import os
import random
import ssl
import urllib.request
from typing import Any

_ODOO_URL = os.environ.get("ODOO_URL", "http://localhost:8069")
# Self-signed cert on the POC's nginx (no real domain for an IP-only box).
_SSL_CONTEXT = ssl._create_unverified_context() if _ODOO_URL.startswith("https://") else None
_ODOO_DB = "odoo"
_ODOO_USER = "admin"
_ODOO_PASSWORD = "admin"
_SUBSIDIARY_NAME = "Northstar Distribution"
_RESELLER_NAME = "Acme Retail"
_PO_REFERENCE = "PO-48213"
_PRODUCTS: list[tuple[str, str, float, float]] = [
    ("WH-SHLF-500", "Steel Shelving Unit - 5 Tier", 189.00, 4),
    ("PK-WRAP-6CS", "Heavy-Duty Pallet Wrap (Case of 6)", 42.50, 12),
    ("SFT-GLV-12PK", "Cut-Resistant Safety Gloves (Pack of 12)", 58.00, 25),
    ("LED-HB-150W", "Warehouse LED High-Bay Light, 150W", 124.75, 8),
]


def _jsonrpc(service: str, method: str, args: list[Any]) -> Any:
    body = json.dumps(
        {
            "jsonrpc": "2.0",
            "method": "call",
            "params": {"service": service, "method": method, "args": args},
            "id": random.randint(1, 1_000_000_000),
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        _ODOO_URL.rstrip("/") + "/jsonrpc",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=30, context=_SSL_CONTEXT) as response:
        parsed = json.loads(response.read())
    if parsed.get("error"):
        error = parsed["error"]
        message = (error.get("data") or {}).get("message") or error.get("message")
        raise RuntimeError(f"Odoo error: {message}")
    return parsed.get("result")


def _authenticate() -> int:
    uid = _jsonrpc("common", "authenticate", [_ODOO_DB, _ODOO_USER, _ODOO_PASSWORD, {}])
    if not uid:
        raise RuntimeError("Odoo authentication failed (admin/admin)")
    return int(uid)


def _execute(
    uid: int, model: str, method: str, args: list[Any], kwargs: dict[str, Any] | None = None
) -> Any:
    return _jsonrpc(
        "object", "execute_kw", [_ODOO_DB, uid, _ODOO_PASSWORD, model, method, args, kwargs or {}]
    )


def main() -> None:
    uid = _authenticate()
    _execute(uid, "res.company", "write", [[1], {"name": _SUBSIDIARY_NAME}])

    partner_ids = _execute(
        uid, "res.partner", "search", [[["name", "=", _RESELLER_NAME]]], {"limit": 1}
    )
    if partner_ids:
        partner_id = int(partner_ids[0])
    else:
        partner_id = int(
            _execute(
                uid,
                "res.partner",
                "create",
                [{"name": _RESELLER_NAME, "company_type": "company", "customer_rank": 1}],
            )
        )

    product_ids: dict[str, int] = {}
    for code, name, price, _qty in _PRODUCTS:
        found = _execute(
            uid, "product.product", "search", [[["default_code", "=", code]]], {"limit": 1}
        )
        if found:
            product_ids[code] = int(found[0])
        else:
            product_ids[code] = int(
                _execute(
                    uid,
                    "product.product",
                    "create",
                    [{"name": name, "default_code": code, "list_price": price}],
                )
            )

    existing_order = _execute(
        uid, "sale.order", "search", [[["client_order_ref", "=", _PO_REFERENCE]]], {"limit": 1}
    )
    if not existing_order:
        order_lines = [
            (0, 0, {"product_id": product_ids[code], "product_uom_qty": qty})
            for code, _name, _price, qty in _PRODUCTS
        ]
        order_id = _execute(
            uid,
            "sale.order",
            "create",
            [
                {
                    "partner_id": partner_id,
                    "client_order_ref": _PO_REFERENCE,
                    "order_line": order_lines,
                }
            ],
        )
        _execute(uid, "sale.order", "action_confirm", [[order_id]])

    print(
        f"seeded: company renamed, partner {_RESELLER_NAME} (id {partner_id}), "
        f"{len(product_ids)} products, order {_PO_REFERENCE}"
    )


if __name__ == "__main__":
    main()
