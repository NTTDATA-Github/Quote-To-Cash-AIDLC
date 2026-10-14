"""JSONPlaceholder Demo ERP adapter — a real adapter against a real public API
(https://jsonplaceholder.typicode.com), kept deliberately small because that API is a
free fake REST backend for prototyping, not a real order-management system.

Stdlib-only HTTP client with explicit timeouts and transient/terminal error
classification (RESILIENCY-10), following odoo_adapter.py's shape. Pure payload
building (build_post_payload) is unit-testable without a server — see
test_jsonplaceholder_demo_erp_adapter.py (mocks _request, not a live service).

Two things this file is honest about, documented in detail in
docs/erps/jsonplaceholder-demo-erp/README.md:

* JSONPlaceholder's public API has no "sales order" concept, no product catalog, and no
  order-status field. The only resource with any kind of real customer identity is
  GET /users/{id} (used directly as the erp_customer_id, fail-closed, no name lookup —
  same reasoning as Odoo's partner_id). Order lines have nowhere real to live, so they
  are serialized as JSON text inside posts.body — a known limitation, not a design
  we'd keep for a real ERP.
* Everything about this account's own extensions beyond JSONPlaceholder's public
  four-field posts schema (userId, id, title, body) is unverified except the one
  human-reviewed mapping below. Status values are not guessed at all (see
  status_mapping.py's _map_jsonplaceholder_demo_erp).
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

from ..application.ports import (
    ErpInvoice,
    ErpPartnerOrder,
    ErpPartnerOrderLine,
    ErpShipment,
    ErpTarget,
    SubmissionResult,
)


class _JsonPlaceholderError(Exception):
    def __init__(self, message: str, *, terminal: bool) -> None:
        super().__init__(message)
        self.terminal = terminal


def build_post_payload(order_payload: dict[str, Any]) -> dict[str, Any]:
    """Pure: turn the ERP-neutral canonical order payload into the JSON body for
    POST /posts.

    title doubles as the idempotency key (platform order_id, FR-A2 — searched before
    create in submit, same reasoning as Odoo's client_order_ref). JSONPlaceholder's
    public posts schema has no field for structured order lines, so they're carried as
    a JSON string in body (demo-backend limitation — see module docstring).
    """
    order_id = str(order_payload.get("order_id") or "")
    lines = order_payload.get("lines") or []
    body = {
        "client_reference": str(order_payload.get("client_reference") or ""),
        "lines": [
            {
                "product_key": str(line.get("product_key") or ""),
                "quantity": str(line.get("quantity") or ""),
                "unit_of_measure": str(line.get("unit_of_measure") or ""),
            }
            for line in lines
        ],
    }
    payload: dict[str, Any] = {"title": order_id, "body": json.dumps(body)}

    # Approved field mapping (96% confidence, human-reviewed — see
    # docs/erps/jsonplaceholder-demo-erp/README.md "Outbound" section): canonical
    # end_customer_name -> this ERP's "name" field. read_payload (the sales/ordering
    # side) does not populate end_customer_name on the order payload today, so this is
    # omitted rather than sent as an empty string until that changes — not a gap in
    # this mapping, a gap in what's upstream of it.
    end_customer_name = order_payload.get("end_customer_name")
    if end_customer_name:
        payload["name"] = str(end_customer_name)
    return payload


class JsonPlaceholderDemoErpAdapter:
    # Declared per ADR-0015. Only "idempotency" is real here: no product catalog to
    # fail closed against (no "fail_closed_product"), no tax/uom/multi-currency concept,
    # and fetch_shipments/fetch_invoices always return [] (no such documents exist in
    # this ERP's public schema) so "partial_fulfillment" is not claimed either.
    capabilities = frozenset({"idempotency"})

    def __init__(self, timeout_seconds: float = 10.0) -> None:
        self._timeout = timeout_seconds

    # --- ErpAdapter port ---
    def submit(self, target: ErpTarget, order_payload: dict[str, Any]) -> SubmissionResult:
        try:
            order_id = order_payload.get("order_id")
            customer_id = self._customer_id(target, order_payload)
            if order_id:
                # Idempotency: search by title == our order_id before creating (FR-A2),
                # same reasoning as Odoo's client_order_ref search. Against
                # JSONPlaceholder's actual public sandbox this will never find a match —
                # POST there is a fake echo that never persists (documented in its own
                # guide) — but the check is still correct code for a real backing store.
                existing = self._request(target, "GET", f"/posts?userId={customer_id}")
                for row in existing or []:
                    if str(row.get("title") or "") == str(order_id):
                        return SubmissionResult(success=True, erp_order_id=str(row["id"]))
            payload = build_post_payload(order_payload)
            payload["userId"] = customer_id
            created = self._request(target, "POST", "/posts", body=payload)
            erp_order_id = str((created or {}).get("id") or "")
            if not erp_order_id:
                raise _JsonPlaceholderError("no id returned by POST /posts", terminal=False)
            return SubmissionResult(success=True, erp_order_id=erp_order_id)
        except _JsonPlaceholderError as exc:
            return SubmissionResult(success=False, error=str(exc), terminal=exc.terminal)

    def fetch_partner_orders(self, target: ErpTarget, partner_id: str) -> list[ErpPartnerOrder]:
        """Posts for this user. A post whose body doesn't parse as our own JSON line
        shape is skipped — same "no recognizable product code -> skip" reasoning Odoo
        applies to a sale order line with no Internal Reference."""
        try:
            rows = self._request(target, "GET", f"/posts?userId={partner_id}")
        except _JsonPlaceholderError:
            return []
        found: list[ErpPartnerOrder] = []
        for row in rows or []:
            try:
                parsed = json.loads(row.get("body") or "")
            except (TypeError, ValueError):
                continue
            if not isinstance(parsed, dict):
                continue
            raw_lines = parsed.get("lines") or []
            lines: list[ErpPartnerOrderLine] = []
            for raw in raw_lines:
                code = str(raw.get("product_key") or "")
                quantity = str(raw.get("quantity") or "")
                if not code or not quantity:
                    continue
                lines.append(ErpPartnerOrderLine(product_key=code, quantity=quantity))
            if not lines or not row.get("id"):
                continue
            found.append(
                ErpPartnerOrder(
                    erp_order_id=str(row["id"]),
                    client_reference=str(
                        parsed.get("client_reference") or row.get("title") or row["id"]
                    ),
                    lines=tuple(lines),
                )
            )
        return found

    def fetch_status(self, target: ErpTarget, erp_order_id: str) -> dict[str, str] | None:
        """GET /posts/{id} is JSONPlaceholder's own, publicly documented way to read one
        resource (a real, working default for that part). What a "status" field would
        actually mean on this account's order record is not public knowledge — see
        status_mapping.py's _map_jsonplaceholder_demo_erp for the TODO."""
        try:
            row = self._request(target, "GET", f"/posts/{erp_order_id}")
        except _JsonPlaceholderError:
            # Same reasoning as OdooAdapter.fetch_status: swallow every failure here
            # (both a 404 and a timeout) — the reconcile sweeper's next poll is already
            # the retry; there's no terminal/transient channel on a plain dict return.
            return None
        if not row:
            return None
        return {"status": str(row.get("status") or "")}

    def fetch_shipments(self, target: ErpTarget, erp_order_id: str) -> list[ErpShipment]:
        """No shipment/delivery document exists in this ERP's public schema."""
        return []

    def fetch_invoices(self, target: ErpTarget, erp_order_id: str) -> list[ErpInvoice]:
        """No invoice document exists in this ERP's public schema."""
        return []

    def cancel(self, target: ErpTarget, erp_order_id: str) -> SubmissionResult:
        """DELETE /posts/{id} — JSONPlaceholder's own documented convention for removing
        a resource; there is no dedicated "cancel" endpoint/field to call instead."""
        try:
            self._request(target, "DELETE", f"/posts/{erp_order_id}")
            return SubmissionResult(success=True, erp_order_id=erp_order_id)
        except _JsonPlaceholderError as exc:
            return SubmissionResult(success=False, error=str(exc), terminal=exc.terminal)

    # --- customer resolution ---
    def _customer_id(self, target: ErpTarget, order_payload: dict[str, Any]) -> int:
        """Fail closed, not a silent auto-create — same reasoning as Odoo's partner_id
        (FR-A1): erp_customer_id is used directly as JSONPlaceholder's own user id, and
        is checked against the real, publicly documented GET /users/{id} endpoint
        before anything is created against it."""
        raw = order_payload.get("erp_customer_id")
        if raw in (None, ""):
            raise _JsonPlaceholderError(
                "no erp_customer_id on the order — the reseller is not linked to an ERP customer",
                terminal=True,
            )
        try:
            customer_id = int(raw)
        except (TypeError, ValueError) as exc:
            raise _JsonPlaceholderError(
                f"erp_customer_id {raw!r} is not a valid JSONPlaceholder user id", terminal=True
            ) from exc
        try:
            user = self._request(target, "GET", f"/users/{customer_id}")
        except _JsonPlaceholderError as exc:
            if exc.terminal:
                raise _JsonPlaceholderError(
                    f"no JSONPlaceholder user with id {customer_id} — sync it before retrying",
                    terminal=True,
                ) from exc
            raise
        if not user:
            raise _JsonPlaceholderError(
                f"no JSONPlaceholder user with id {customer_id} — sync it before retrying",
                terminal=True,
            )
        return customer_id

    # --- HTTP plumbing ---
    def _request(
        self, target: ErpTarget, method: str, path: str, body: dict[str, Any] | None = None
    ) -> Any:
        # JSONPlaceholder's public API requires no authentication at all — it's a free,
        # open fake REST API, documented at https://jsonplaceholder.typicode.com/guide/.
        # Assumption from JSONPlaceholder's public API documentation, to be verified
        # against the real account: if a real backing account for this ERP type needs a
        # bearer token, it goes in secret_ref/ErpTarget.secret and is sent below —
        # nothing is sent when there is no secret configured, matching today's docs.
        headers = {"Content-Type": "application/json; charset=UTF-8"}
        if target.secret:
            headers["Authorization"] = "Bearer " + target.secret
        data = json.dumps(body).encode("utf-8") if body is not None else None
        request = urllib.request.Request(
            target.base_url.rstrip("/") + path,
            data=data,
            headers=headers,
            method=method,
        )
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as response:
                raw = response.read()
                return json.loads(raw) if raw else None
        except urllib.error.HTTPError as exc:
            # 4xx (validation, not found, bad auth) won't fix itself on retry; 5xx might.
            terminal = not (500 <= exc.code < 600)
            raise _JsonPlaceholderError("HTTP " + str(exc.code), terminal=terminal) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise _JsonPlaceholderError(
                "cannot reach JSONPlaceholder Demo ERP: " + str(exc), terminal=False
            ) from exc
