"""Seed the local demo through the running API (memory profile).

Run after `uvicorn src.api.app:app` starts with APP_PROFILE=memory. The in-memory state
lives in that process, so run this once per API start.

- In Odoo (JSON-RPC, admin/admin): renames company 1, creates the reseller customer, a small
  industrial-distributor catalog, and one confirmed sales order with a PO reference. Skip
  with ODOO_PARTNER_ID=<partner id> when Odoo isn't running.
- Through the operator GraphQL API: registers the Odoo and NetSuite connections, binds the
  reseller to both, and routes a subsidiary to each.
- Through the reseller GraphQL API: registers the local reseller webhook endpoint and writes
  its signing secret to .local/reseller-secret for scripts/dev_webhook_receiver.py.

Connection secrets go through the env secret store, so the API must start with
ODOO_WEBHOOK_SECRET and NETSUITE_WEBHOOK_SECRET set (scripts/local.sh does this).

Usage:
    python -m scripts.seed_demo
"""

from __future__ import annotations

import json
import os
import random
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

API_URL = os.environ.get("API_URL", "http://127.0.0.1:8000")
KEYCLOAK_REALM_URL = os.environ.get("KEYCLOAK_REALM_URL", "http://localhost:8080/realms/o2c")
KEYCLOAK_CLIENT_ID = os.environ.get("KEYCLOAK_CLIENT_ID", "o2c-portal")
SEED_USER = os.environ.get("SEED_USER", "operator1")
SEED_PASSWORD = os.environ.get("SEED_PASSWORD", "operator1")
RESELLER_SECRET_FILE = Path(".local/reseller-secret")

ODOO_URL = os.environ.get("ODOO_URL", "http://localhost:8069")
ODOO_DB = "odoo"
ODOO_USER = "admin"
ODOO_PASSWORD = "admin"
ODOO_WEBHOOK_SECRET_REF = "env:ODOO_WEBHOOK_SECRET"
ODOO_SUBSIDIARY_NAME = "Northstar Distribution"
ODOO_PO_REFERENCE = "PO-48213"
# (default_code, name, list_price, order quantity) — a generic industrial-distributor
# catalog, standing in for whatever a real client's products are.
PRODUCTS: list[tuple[str, str, float, float]] = [
    ("WH-SHLF-500", "Steel Shelving Unit - 5 Tier", 189.00, 4),
    ("PK-WRAP-6CS", "Heavy-Duty Pallet Wrap (Case of 6)", 42.50, 12),
    ("SFT-GLV-12PK", "Cut-Resistant Safety Gloves (Pack of 12)", 58.00, 25),
    ("LED-HB-150W", "Warehouse LED High-Bay Light, 150W", 124.75, 8),
]
RESELLER_NAME = "Acme Retail"

NETSUITE_URL = os.environ.get("NETSUITE_URL", "http://127.0.0.1:8075")
NETSUITE_CUSTOMER_ID = "101"
NETSUITE_SUBSIDIARY_NAME = "Northwind Trading Co."
NETSUITE_WEBHOOK_SECRET_REF = "env:NETSUITE_WEBHOOK_SECRET"
NETSUITE_CREDENTIALS = {
    "account_id": "TSTDRV1458972",
    "consumer_key": "a1b2c3d4e5f60718293a4b5c6d7e8f90",
    "token_id": "90f8e7d6c5b4a3920817f6e5d4c3b2a1",
}
# NetSuite TBA: the adapter reads both components from one JSON secret.
NETSUITE_TBA_SECRET = json.dumps(
    {
        "consumer_secret": "7c1f9a4b2e8d46a3b5c0e9f1a7d2b4c6",
        "token_secret": "a3b5c0e9f1a7d2b4c67c1f9a4b2e8d46",
    }
)

RESELLER_MOCK_URL = "http://127.0.0.1:8090/hooks"


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
        ODOO_URL.rstrip("/") + "/jsonrpc",
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
    uid = _jsonrpc("common", "authenticate", [ODOO_DB, ODOO_USER, ODOO_PASSWORD, {}])
    if not uid:
        raise RuntimeError("Odoo authentication failed (admin/admin)")
    return int(uid)


def _execute(
    uid: int, model: str, method: str, args: list[Any], kwargs: dict[str, Any] | None = None
) -> Any:
    return _jsonrpc(
        "object", "execute_kw", [ODOO_DB, uid, ODOO_PASSWORD, model, method, args, kwargs or {}]
    )


def _seed_odoo() -> str:
    """Returns the reseller partner's Odoo id, as a string, for the binding."""
    uid = _authenticate()
    _execute(uid, "res.company", "write", [[1], {"name": ODOO_SUBSIDIARY_NAME}])

    partner_ids = _execute(
        uid, "res.partner", "search", [[["name", "=", RESELLER_NAME]]], {"limit": 1}
    )
    if partner_ids:
        partner_id = int(partner_ids[0])
    else:
        partner_id = int(
            _execute(
                uid,
                "res.partner",
                "create",
                [{"name": RESELLER_NAME, "company_type": "company", "customer_rank": 1}],
            )
        )

    product_ids: dict[str, int] = {}
    for code, name, price, _qty in PRODUCTS:
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
        uid, "sale.order", "search", [[["client_order_ref", "=", ODOO_PO_REFERENCE]]], {"limit": 1}
    )
    if not existing_order:
        order_lines = [
            (0, 0, {"product_id": product_ids[code], "product_uom_qty": qty})
            for code, _name, _price, qty in PRODUCTS
        ]
        order_id = _execute(
            uid,
            "sale.order",
            "create",
            [
                {
                    "partner_id": partner_id,
                    "client_order_ref": ODOO_PO_REFERENCE,
                    "order_line": order_lines,
                }
            ],
        )
        _execute(uid, "sale.order", "action_confirm", [[order_id]])

    return str(partner_id)


def _access_token() -> str:
    """The demo operator's Keycloak token. Its tenant_id claim scopes every call below."""
    body = urllib.parse.urlencode(
        {
            "grant_type": "password",
            "client_id": KEYCLOAK_CLIENT_ID,
            "username": SEED_USER,
            "password": SEED_PASSWORD,
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        f"{KEYCLOAK_REALM_URL}/protocol/openid-connect/token",
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return str(json.loads(response.read())["access_token"])


def _gql(path: str, query: str, variables: dict[str, Any]) -> dict[str, Any]:
    body = json.dumps({"query": query, "variables": variables}).encode("utf-8")
    request = urllib.request.Request(
        f"{API_URL}{path}",
        data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {_access_token()}",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        parsed = json.loads(response.read())
    if parsed.get("errors"):
        raise RuntimeError(f"GraphQL error on {path}: {parsed['errors'][0]['message']}")
    return parsed["data"]


def _operator(query: str, variables: dict[str, Any]) -> dict[str, Any]:
    return _gql("/graphql/operator", query, variables)


_REGISTER_CONNECTION = """
mutation($erpType: String!, $label: String!, $baseUrl: String!, $credentials: JSON!,
         $secret: String!, $webhookSecretRef: String!) {
  registerConnection(erpType: $erpType, instanceLabel: $label, baseUrl: $baseUrl,
    credentials: $credentials,
    auth: { authType: "NONE", params: {}, secret: $secret },
    webhookSecretRef: $webhookSecretRef) { connectionId }
}
"""
_CREATE_BINDING = """
mutation($connectionId: String!, $erpCustomerId: String!, $name: String!) {
  createBinding(tenantId: "tnt_demo", connectionId: $connectionId,
    erpCustomerId: $erpCustomerId, name: $name) { bindingId }
}
"""
_VERIFY_BINDING = """
mutation($bindingId: String!) { verifyBinding(bindingId: $bindingId) { bindingId } }
"""
_CREATE_SUBSIDIARY = """
mutation($name: String!) {
  createSubsidiary(name: $name, country: "US", language: "en_US") { subsidiaryId }
}
"""
_SET_ERP_ROUTE = """
mutation($subsidiaryId: String!, $connectionId: String!, $erpCompanyId: String!) {
  setErpRoute(subsidiaryId: $subsidiaryId, connectionId: $connectionId,
    erpCompanyId: $erpCompanyId) { subsidiaryId }
}
"""
_RENAME_RESELLER = """
mutation($name: String!) { renameReseller(tenantId: "tnt_demo", name: $name) { tenantId } }
"""
_REGISTER_WEBHOOK = """
mutation($name: String!, $url: String!) {
  registerWebhookEndpoint(name: $name, url: $url) { signingSecret }
}
"""


def _seed_operator(odoo_partner_id: str) -> None:
    _operator(_RENAME_RESELLER, {"name": RESELLER_NAME})

    odoo = _operator(
        _REGISTER_CONNECTION,
        {
            "erpType": "ODOO",
            "label": "Odoo",
            "baseUrl": ODOO_URL,
            "credentials": {"database": ODOO_DB, "username": ODOO_USER},
            "secret": ODOO_PASSWORD,
            "webhookSecretRef": ODOO_WEBHOOK_SECRET_REF,
        },
    )["registerConnection"]
    odoo_id = odoo["connectionId"]
    binding = _operator(
        _CREATE_BINDING,
        {"connectionId": odoo_id, "erpCustomerId": odoo_partner_id, "name": RESELLER_NAME},
    )["createBinding"]
    _operator(_VERIFY_BINDING, {"bindingId": binding["bindingId"]})
    subsidiary = _operator(_CREATE_SUBSIDIARY, {"name": ODOO_SUBSIDIARY_NAME})["createSubsidiary"]
    _operator(
        _SET_ERP_ROUTE,
        {"subsidiaryId": subsidiary["subsidiaryId"], "connectionId": odoo_id, "erpCompanyId": "1"},
    )

    netsuite = _operator(
        _REGISTER_CONNECTION,
        {
            "erpType": "NETSUITE",
            "label": "NetSuite",
            "baseUrl": NETSUITE_URL,
            "credentials": NETSUITE_CREDENTIALS,
            "secret": NETSUITE_TBA_SECRET,
            "webhookSecretRef": NETSUITE_WEBHOOK_SECRET_REF,
        },
    )["registerConnection"]
    netsuite_id = netsuite["connectionId"]
    binding = _operator(
        _CREATE_BINDING,
        {
            "connectionId": netsuite_id,
            "erpCustomerId": NETSUITE_CUSTOMER_ID,
            "name": RESELLER_NAME,
        },
    )["createBinding"]
    _operator(_VERIFY_BINDING, {"bindingId": binding["bindingId"]})
    subsidiary = _operator(_CREATE_SUBSIDIARY, {"name": NETSUITE_SUBSIDIARY_NAME})[
        "createSubsidiary"
    ]
    _operator(
        _SET_ERP_ROUTE,
        {
            "subsidiaryId": subsidiary["subsidiaryId"],
            "connectionId": netsuite_id,
            "erpCompanyId": "NS1",
        },
    )

    print(f"connections: Odoo {odoo_id} (partner {odoo_partner_id}), NetSuite {netsuite_id}")
    odoo_secret = os.environ.get("ODOO_WEBHOOK_SECRET", "odoo-webhook-demo")
    print(f"odoo webhook: {API_URL}/erp/webhook/{odoo_id}/{odoo_secret}")


def _seed_reseller() -> None:
    data = _gql(
        "/graphql/reseller",
        _REGISTER_WEBHOOK,
        {"name": "Local reseller mock", "url": RESELLER_MOCK_URL},
    )
    RESELLER_SECRET_FILE.parent.mkdir(parents=True, exist_ok=True)
    secret = data["registerWebhookEndpoint"]["signingSecret"]
    RESELLER_SECRET_FILE.write_text(secret, encoding="utf-8")
    print(f"reseller webhook -> {RESELLER_MOCK_URL} (secret in {RESELLER_SECRET_FILE})")


def main() -> None:
    partner_id = os.environ.get("ODOO_PARTNER_ID") or _seed_odoo()
    _seed_operator(partner_id)
    _seed_reseller()
    print("demo data seeded")


if __name__ == "__main__":
    main()
