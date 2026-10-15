"""Seed demo data for local development (idempotent).

Creates realistic data on both sides, not just placeholders:
- In Odoo (JSON-RPC, admin/admin): renames company 1 to a real-looking distributor name,
  creates a real-looking reseller customer, a small industrial-distributor product
  catalog with real SKUs (never a product literally named "DEMO-BOX"), and one confirmed
  sales order for that customer with a real-looking PO reference.
- In Postgres: one Odoo connection and a verified binding, using the *actual* partner id
  Odoo just returned — never a guessed constant (this used to hardcode '10', which had
  already drifted from what `scripts/local.sh`'s own banner claimed).

Sales orders are read from Odoo for that partner; this app does not create them — the
one this script creates in Odoo is standing in for a reseller's own real order. The
subsidiary's erp_company_id is Odoo's res.company id (company 1). A quotation whose
company id is not recorded on a subsidiary is not adopted.

Usage:
    DATABASE_URL=postgresql+psycopg2://portal:portal@localhost:5432/portal \\
    AWS_ENDPOINT_URL=http://localhost:4566 \\
        python -m scripts.seed_demo
"""

from __future__ import annotations

import json
import os
import random
import urllib.error
import urllib.request
from typing import Any

from sqlalchemy import create_engine, text
from src.shared.secrets.aws import SecretsManagerSecretStore
from src.shared.secrets.store import SecretNotFound

_LOGIN_SECRET = "local:odoo-admin-secret"
_WEBHOOK_SECRET = "local:odoo-webhook-demo-secret"
# Fixed id + secret so `local.sh up` registers the mock once. A generated id would
# insert another endpoint on every start, and every event would be delivered twice.
_RESELLER_ENDPOINT_ID = "whep_local_demo"
_RESELLER_ENDPOINT_SECRET = "local:reseller-webhook-secret"
_OUTBOUND_WEBHOOK_SECRET = "whsec_local_dev"
_RESELLER_MOCK_URL = "http://127.0.0.1:8090/hooks"

_ODOO_URL = "http://localhost:8069"
_ODOO_DB = "odoo"
_ODOO_USER = "admin"
_ODOO_PASSWORD = "admin"
_SUBSIDIARY_NAME = "Northstar Distribution"
_RESELLER_NAME = "Acme Retail"
_PO_REFERENCE = "PO-48213"
# (default_code, name, list_price, order quantity) — a generic industrial-distributor
# catalog, standing in for whatever a real client's products are.
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
    with urllib.request.urlopen(request, timeout=30) as response:
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


def _seed_odoo() -> str:
    """Returns the reseller partner's Odoo id, as a string, for the Postgres binding."""
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

    return str(partner_id)


_STATEMENTS = [
    text(
        """
        INSERT INTO erp_connections
            (connection_id, erp_type, instance_label, base_url, credentials, secret_ref,
             webhook_secret_ref, status)
        VALUES
            ('conn_odoo_local', 'ODOO', 'Odoo', 'http://localhost:8069',
             '{"database":"odoo","username":"admin"}'::jsonb,
             :login_secret, :webhook_secret, 'ACTIVE')
        ON CONFLICT (connection_id) DO UPDATE SET
            instance_label = EXCLUDED.instance_label,
            base_url = EXCLUDED.base_url,
            credentials = EXCLUDED.credentials,
            secret_ref = EXCLUDED.secret_ref,
            webhook_secret_ref = EXCLUDED.webhook_secret_ref
        """
    ),
    text(
        """
        INSERT INTO resellers (tenant_id, name)
        VALUES ('tnt_demo', :reseller_name)
        ON CONFLICT (tenant_id) DO UPDATE SET name = EXCLUDED.name
        """
    ),
    text(
        """
        INSERT INTO tenant_connection_bindings
            (binding_id, tenant_id, connection_id, erp_customer_id, status)
        VALUES
            ('bind_demo', 'tnt_demo', 'conn_odoo_local', :erp_customer_id, 'VERIFIED')
        ON CONFLICT (binding_id) DO UPDATE SET erp_customer_id = EXCLUDED.erp_customer_id
        """
    ),
    text(
        """
        INSERT INTO subsidiaries (subsidiary_id, name, country, language)
        VALUES ('sub_demo', :subsidiary_name, 'US', 'en_US')
        ON CONFLICT (subsidiary_id) DO UPDATE SET name = EXCLUDED.name
        """
    ),
    text(
        """
        INSERT INTO subsidiary_routes (subsidiary_id, connection_id, erp_company_id)
        VALUES ('sub_demo', 'conn_odoo_local', '1')
        ON CONFLICT (subsidiary_id) DO UPDATE SET
            connection_id = EXCLUDED.connection_id,
            erp_company_id = EXCLUDED.erp_company_id
        """
    ),
    text(
        """
        INSERT INTO webhook_endpoints
            (endpoint_id, tenant_id, name, url, secret_ref, event_types, is_active)
        VALUES
            (:endpoint_id, 'tnt_demo', 'Local reseller mock', :mock_url, :endpoint_secret,
             NULL, TRUE)
        ON CONFLICT (endpoint_id) DO UPDATE SET
            name = EXCLUDED.name,
            url = EXCLUDED.url,
            secret_ref = EXCLUDED.secret_ref,
            is_active = TRUE
        """
    ),
]


def _put_secrets(outbound_refs: list[str]) -> None:
    endpoint = os.environ.get("AWS_ENDPOINT_URL")
    if not endpoint:
        print("AWS_ENDPOINT_URL is unset — Odoo login secret was not stored")
        return
    store = SecretsManagerSecretStore(
        endpoint_url=endpoint, region_name=os.environ.get("AWS_DEFAULT_REGION", "us-east-1")
    )
    store.put_secret(_LOGIN_SECRET, "admin")
    store.put_secret(_WEBHOOK_SECRET, "odoo-webhook-demo")
    store.put_secret(_RESELLER_ENDPOINT_SECRET, _OUTBOUND_WEBHOOK_SECRET)
    restored = 0
    for secret_ref in outbound_refs:
        try:
            store.get_secret(secret_ref)
        except SecretNotFound:
            store.put_secret(secret_ref, _OUTBOUND_WEBHOOK_SECRET)
            restored += 1
    if restored:
        print(f"restored {restored} outbound webhook signing secret(s)")


def main() -> None:
    url = os.environ.get(
        "DATABASE_URL", "postgresql+psycopg2://portal:portal@localhost:5432/portal"
    )
    erp_customer_id = _seed_odoo()
    engine = create_engine(url, future=True)
    params = {
        "login_secret": _LOGIN_SECRET,
        "webhook_secret": _WEBHOOK_SECRET,
        "erp_customer_id": erp_customer_id,
        "subsidiary_name": _SUBSIDIARY_NAME,
        "reseller_name": _RESELLER_NAME,
        "endpoint_id": _RESELLER_ENDPOINT_ID,
        "mock_url": _RESELLER_MOCK_URL,
        "endpoint_secret": _RESELLER_ENDPOINT_SECRET,
    }
    with engine.begin() as connection:
        for statement in _STATEMENTS:
            connection.execute(statement, params)
        outbound_refs = [
            row[0] for row in connection.execute(text("SELECT secret_ref FROM webhook_endpoints"))
        ]
    _put_secrets(outbound_refs)
    print(
        f"demo data seeded (connection, binding -> Odoo partner {erp_customer_id}, "
        f"subsidiary, reseller webhook {_RESELLER_ENDPOINT_ID} -> {_RESELLER_MOCK_URL})"
    )


if __name__ == "__main__":
    main()
