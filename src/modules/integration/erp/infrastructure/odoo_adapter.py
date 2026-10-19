"""Real Odoo adapter (JSON-RPC) implementing the ErpAdapter port.

Stdlib-only client with explicit timeouts and transient/terminal error classification
(RESILIENCY-10). Exercised against a live Odoo (docker stack); not run in the
offline sandbox. Pure payload building is unit-testable without a server.
"""

from __future__ import annotations

import json
import random
import urllib.error
import urllib.request
from typing import Any

from ..application.ports import (
    ErpInvoice,
    ErpPartnerOrder,
    ErpPartnerOrderLine,
    ErpShipment,
    ErpShipmentLine,
    ErpTarget,
    SubmissionResult,
)


class _OdooError(Exception):
    def __init__(self, message: str, *, terminal: bool) -> None:
        super().__init__(message)
        self.terminal = terminal


def build_sale_order_lines(order_payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Pure: turn the ERP-neutral payload into the fields we resolve into Odoo order lines.

    `unit_price`/`tax_rates`/`line_discount` are the JSON-safe payload shapes from
    `money.py` (`{"amount": str, "currency": str}` / list of `{"code","rate","inclusive"}`)
    — this function only reads them, resolving into real Odoo ids happens in `submit`."""
    lines: list[dict[str, Any]] = []
    for raw in order_payload.get("lines", []) or []:
        product_key = str(raw.get("product_key") or "UNKNOWN")
        try:
            qty = float(raw.get("quantity", 0) or 0)
        except (TypeError, ValueError):
            qty = 0.0
        unit_price = raw.get("unit_price")
        line_discount = raw.get("line_discount")
        net_unit_price = None
        if unit_price is not None:
            price = float(unit_price["amount"])
            discount = float(line_discount["amount"]) if line_discount is not None else 0.0
            net_unit_price = max(price - discount, 0.0)
        lines.append(
            {
                "product_key": product_key,
                "quantity": max(qty, 0.0) or 1.0,
                "unit_of_measure": str(raw.get("unit_of_measure") or ""),
                "unit_price": net_unit_price,
                "currency": unit_price["currency"] if unit_price is not None else None,
                "tax_codes": [t["code"] for t in (raw.get("tax_rates") or [])],
            }
        )
    return lines


class OdooAdapter:
    # Declared per ADR-0015. `partial_fulfillment` is the done-picking read in
    # `fetch_shipments`. `multi_currency` stays absent: one currency assumed throughout.
    capabilities = frozenset(
        {"tax", "uom", "idempotency", "fail_closed_product", "partial_fulfillment"}
    )

    def __init__(self, timeout_seconds: float = 10.0) -> None:
        self._timeout = timeout_seconds

    # --- ErpAdapter port ---
    def submit(self, target: ErpTarget, order_payload: dict[str, Any]) -> SubmissionResult:
        try:
            uid = self._authenticate(target)
            # Idempotency key is the platform order id (FR-A2) — stable and unique, unlike
            # the reseller's client_reference. Written to client_order_ref on create and
            # searched here first so a retried submit (e.g. after a timeout where the first
            # attempt actually succeeded) returns the existing order instead of duplicating.
            order_id = order_payload.get("order_id")
            if order_id:
                existing = self._execute(
                    target,
                    uid,
                    "sale.order",
                    "search_read",
                    [[["client_order_ref", "=", str(order_id)]]],
                    {"fields": ["name"], "limit": 1},
                )
                if existing:
                    return SubmissionResult(success=True, erp_order_id=existing[0]["name"])
            # The customer is the reseller's ERP customer id from the binding (FR-A1) —
            # sent as the Odoo partner directly, never a name-based auto-create.
            partner_id = self._partner_id(order_payload)
            order_lines = []
            for line in build_sale_order_lines(order_payload):
                product_id = self._resolve_product(target, uid, line["product_key"])
                line_vals: dict[str, Any] = {
                    "product_id": product_id,
                    "product_uom_qty": line["quantity"],
                }
                if line["unit_price"] is not None:
                    # Net of any flat per-unit discount already subtracted in
                    # build_sale_order_lines — Odoo's own `discount` field is a
                    # percentage, which doesn't fit a flat-amount discount cleanly.
                    line_vals["price_unit"] = line["unit_price"]
                uom_id = self._resolve_uom(target, uid, line["unit_of_measure"])
                if uom_id is not None:
                    line_vals["product_uom"] = uom_id
                tax_ids = [
                    tax_id
                    for tax_id in (
                        self._resolve_tax(target, uid, code) for code in line["tax_codes"]
                    )
                    if tax_id is not None
                ]
                if tax_ids:
                    line_vals["tax_id"] = [(6, 0, tax_ids)]
                order_lines.append((0, 0, line_vals))
            vals: dict[str, Any] = {"partner_id": partner_id, "order_line": order_lines}
            if order_id:
                vals["client_order_ref"] = str(order_id)
            order_id = self._execute(target, uid, "sale.order", "create", [vals])
            record = self._execute(target, uid, "sale.order", "read", [[order_id], ["name"]])
            name = record[0]["name"] if record else str(order_id)
            return SubmissionResult(success=True, erp_order_id=name)
        except _OdooError as exc:
            return SubmissionResult(success=False, error=str(exc), terminal=exc.terminal)

    def fetch_partner_orders(self, target: ErpTarget, partner_id: str) -> list[ErpPartnerOrder]:
        """Sales orders that already exist for this partner. We do not create them."""
        try:
            pid = int(partner_id)
        except (TypeError, ValueError):
            return []
        try:
            uid = self._authenticate(target)
            orders = self._execute(
                target,
                uid,
                "sale.order",
                "search_read",
                [[["partner_id", "=", pid]]],
                {"fields": ["name", "client_order_ref", "order_line", "currency_id", "company_id"]},
            )
            found: list[ErpPartnerOrder] = []
            for order in orders:
                line_ids = order.get("order_line") or []
                if not line_ids or not order.get("name"):
                    continue
                raw_lines = self._execute(
                    target,
                    uid,
                    "sale.order.line",
                    "read",
                    [line_ids],
                    {"fields": ["product_id", "product_uom_qty", "price_unit", "display_type"]},
                )
                product_ids = [
                    line["product_id"][0]
                    for line in raw_lines
                    if line.get("product_id")
                    and line.get("display_type") in (False, None, "product")
                ]
                codes: dict[int, str] = {}
                if product_ids:
                    products = self._execute(
                        target,
                        uid,
                        "product.product",
                        "read",
                        [product_ids],
                        {"fields": ["default_code"]},
                    )
                    codes = {int(row["id"]): str(row.get("default_code") or "") for row in products}
                currency = "USD"
                currency_field = order.get("currency_id")
                if isinstance(currency_field, list | tuple) and len(currency_field) > 1:
                    currency = str(currency_field[1]) or "USD"
                company = ""
                company_field = order.get("company_id")
                if isinstance(company_field, list | tuple) and company_field:
                    company = str(company_field[0])
                lines: list[ErpPartnerOrderLine] = []
                for line in raw_lines:
                    if not line.get("product_id") or line.get("display_type") not in (
                        False,
                        None,
                        "product",
                    ):
                        continue
                    code = codes.get(int(line["product_id"][0]), "")
                    quantity = line.get("product_uom_qty") or 0
                    if not code or not quantity:
                        continue
                    lines.append(
                        ErpPartnerOrderLine(
                            product_key=code,
                            quantity=str(quantity),
                            unit_price=str(line.get("price_unit") or ""),
                            currency=currency,
                        )
                    )
                if not lines:
                    continue
                name = str(order["name"])
                found.append(
                    ErpPartnerOrder(
                        erp_order_id=name,
                        client_reference=str(order.get("client_order_ref") or name),
                        lines=tuple(lines),
                        erp_company_id=company,
                    )
                )
            return found
        except _OdooError:
            return []

    def fetch_status(self, target: ErpTarget, erp_order_id: str) -> dict[str, str] | None:
        try:
            uid = self._authenticate(target)
            rows = self._execute(
                target,
                uid,
                "sale.order",
                "search_read",
                [[["name", "=", erp_order_id]]],
                {"fields": ["state", "invoice_status"], "limit": 1},
            )
            if not rows:
                return None
            return {
                "state": str(rows[0].get("state") or ""),
                "invoice_status": str(rows[0].get("invoice_status") or ""),
            }
        except _OdooError:
            return None

    def fetch_shipments(self, target: ErpTarget, erp_order_id: str) -> list[ErpShipment]:
        """Done `stock.picking`s on this sales order. The picking name is the proof of delivery."""
        try:
            uid = self._authenticate(target)
            orders = self._execute(
                target,
                uid,
                "sale.order",
                "search_read",
                [[["name", "=", erp_order_id]]],
                {"fields": ["picking_ids"], "limit": 1},
            )
            if not orders or not orders[0].get("picking_ids"):
                return []
            pickings = self._execute(
                target,
                uid,
                "stock.picking",
                "read",
                [orders[0]["picking_ids"]],
                {"fields": ["name", "state", "move_ids"]},
            )
            shipments: list[ErpShipment] = []
            for picking in pickings:
                if picking.get("state") != "done" or not picking.get("move_ids"):
                    continue
                moves = self._execute(
                    target,
                    uid,
                    "stock.move",
                    "read",
                    [picking["move_ids"]],
                    {"fields": ["product_id", "quantity", "state"]},
                )
                product_ids = [
                    move["product_id"][0]
                    for move in moves
                    if move.get("state") == "done" and move.get("product_id")
                ]
                codes: dict[int, str] = {}
                if product_ids:
                    products = self._execute(
                        target,
                        uid,
                        "product.product",
                        "read",
                        [product_ids],
                        {"fields": ["default_code"]},
                    )
                    codes = {int(row["id"]): str(row.get("default_code") or "") for row in products}
                lines: list[ErpShipmentLine] = []
                for move in moves:
                    if move.get("state") != "done" or not move.get("product_id"):
                        continue
                    code = codes.get(int(move["product_id"][0]), "")
                    quantity = move.get("quantity") or 0
                    if not code or not quantity:
                        continue
                    lines.append(ErpShipmentLine(product_key=code, quantity=str(quantity)))
                if not lines:
                    continue
                shipments.append(
                    ErpShipment(
                        erp_shipment_id=str(picking["id"]),
                        lines=tuple(lines),
                        proof_of_delivery=str(picking.get("name") or picking["id"]),
                    )
                )
            return shipments
        except _OdooError:
            return []

    def fetch_invoices(self, target: ErpTarget, erp_order_id: str) -> list[ErpInvoice]:
        """Posted customer invoices on this sales order. Credit notes are skipped."""
        try:
            uid = self._authenticate(target)
            orders = self._execute(
                target,
                uid,
                "sale.order",
                "search_read",
                [[["name", "=", erp_order_id]]],
                {"fields": ["invoice_ids"], "limit": 1},
            )
            if not orders or not orders[0].get("invoice_ids"):
                return []
            moves = self._execute(
                target,
                uid,
                "account.move",
                "read",
                [orders[0]["invoice_ids"]],
                {"fields": ["name", "state", "move_type", "invoice_line_ids"]},
            )
            invoices: list[ErpInvoice] = []
            for move in moves:
                if move.get("state") != "posted" or move.get("move_type") != "out_invoice":
                    continue
                if not move.get("invoice_line_ids"):
                    continue
                raw_lines = self._execute(
                    target,
                    uid,
                    "account.move.line",
                    "read",
                    [move["invoice_line_ids"]],
                    {"fields": ["product_id", "quantity", "display_type"]},
                )
                product_ids = [
                    line["product_id"][0]
                    for line in raw_lines
                    if line.get("product_id")
                    and line.get("display_type") in (False, None, "product")
                ]
                codes: dict[int, str] = {}
                if product_ids:
                    products = self._execute(
                        target,
                        uid,
                        "product.product",
                        "read",
                        [product_ids],
                        {"fields": ["default_code"]},
                    )
                    codes = {int(row["id"]): str(row.get("default_code") or "") for row in products}
                lines: list[ErpShipmentLine] = []
                for line in raw_lines:
                    if not line.get("product_id") or line.get("display_type") not in (
                        False,
                        None,
                        "product",
                    ):
                        continue
                    code = codes.get(int(line["product_id"][0]), "")
                    quantity = line.get("quantity") or 0
                    if not code or not quantity:
                        continue
                    lines.append(ErpShipmentLine(product_key=code, quantity=str(quantity)))
                if not lines:
                    continue
                invoices.append(
                    ErpInvoice(
                        erp_invoice_id=str(move["id"]),
                        lines=tuple(lines),
                        number=str(move.get("name") or move["id"]),
                    )
                )
            return invoices
        except _OdooError:
            return []

    def cancel(self, target: ErpTarget, erp_order_id: str) -> SubmissionResult:
        try:
            uid = self._authenticate(target)
            rows = self._execute(
                target,
                uid,
                "sale.order",
                "search_read",
                [[["name", "=", erp_order_id]]],
                {"fields": ["id"], "limit": 1},
            )
            if not rows:
                return SubmissionResult(success=False, error="order not found", terminal=True)
            self._execute(target, uid, "sale.order", "action_cancel", [[rows[0]["id"]]])
            return SubmissionResult(success=True, erp_order_id=erp_order_id)
        except _OdooError as exc:
            return SubmissionResult(success=False, error=str(exc), terminal=exc.terminal)

    # --- JSON-RPC plumbing ---
    def _authenticate(self, target: ErpTarget) -> int:
        database = target.credentials.get("database", "")
        username = target.credentials.get("username", "")
        uid = self._jsonrpc(
            target, "common", "authenticate", [database, username, target.secret, {}]
        )
        if not uid:
            raise _OdooError("authentication failed", terminal=True)
        return int(uid)

    def _execute(
        self,
        target: ErpTarget,
        uid: int,
        model: str,
        method: str,
        args: list[Any],
        kwargs: dict[str, Any] | None = None,
    ) -> Any:
        database = target.credentials.get("database", "")
        return self._jsonrpc(
            target,
            "object",
            "execute_kw",
            [database, uid, target.secret, model, method, args, kwargs or {}],
        )

    @staticmethod
    def _partner_id(order_payload: dict[str, Any]) -> int:
        """The order is placed AS the reseller's ERP customer (FR-A1): `erp_customer_id`
        is Odoo's own `res.partner` id, from the verified binding. No name-based
        auto-create anymore — a missing/invalid customer id is a terminal error, not a
        silent invention of a new partner."""
        raw = order_payload.get("erp_customer_id")
        if raw in (None, ""):
            raise _OdooError(
                "no erp_customer_id on the order — the reseller is not linked to an ERP customer",
                terminal=True,
            )
        try:
            return int(raw)
        except (TypeError, ValueError) as exc:
            raise _OdooError(
                f"erp_customer_id {raw!r} is not a valid Odoo partner id", terminal=True
            ) from exc

    def _resolve_product(self, target: ErpTarget, uid: int, code: str) -> int:
        """Fail closed, not silent auto-create: by the time this runs, `routing.py` has
        already confirmed `code` is a real SKU in *our* catalog (the `UNKNOWN_ITEM`
        check). If it still has no matching Odoo product, that's catalog drift between
        our system and Odoo worth a human looking at — not something to paper over by
        inventing a new Odoo product with no price, no category, no real setup."""
        found = self._execute(
            target, uid, "product.product", "search", [[["default_code", "=", code]]], {"limit": 1}
        )
        if found:
            return int(found[0])
        raise _OdooError(
            f"no Odoo product with default_code '{code}' — sync it in Odoo before retrying",
            terminal=True,
        )

    def _resolve_uom(self, target: ErpTarget, uid: int, name: str) -> int | None:
        """Graceful degradation, not fail-closed: an unmatched UoM name falls back to the
        product's default unit (today's behavior) rather than blocking the whole order —
        unlike an unknown product, a UoM-naming mismatch isn't catalog drift worth
        stopping delivery for."""
        if not name:
            return None
        found = self._execute(
            target, uid, "uom.uom", "search", [[["name", "=", name]]], {"limit": 1}
        )
        return int(found[0]) if found else None

    def _resolve_tax(self, target: ErpTarget, uid: int, code: str) -> int | None:
        """Same graceful-degradation reasoning as `_resolve_uom` — no matching Odoo tax
        means the line goes out with no tax, not a blocked order; a missing tax config in
        Odoo is visible in Odoo itself, not silently invented here."""
        if not code:
            return None
        found = self._execute(
            target, uid, "account.tax", "search", [[["name", "=", code]]], {"limit": 1}
        )
        return int(found[0]) if found else None

    def _jsonrpc(self, target: ErpTarget, service: str, method: str, args: list[Any]) -> Any:
        body = json.dumps(
            {
                "jsonrpc": "2.0",
                "method": "call",
                "params": {"service": service, "method": method, "args": args},
                "id": random.randint(1, 1_000_000_000),
            }
        ).encode("utf-8")
        request = urllib.request.Request(
            target.base_url.rstrip("/") + "/jsonrpc",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as response:
                parsed = json.loads(response.read())
        except urllib.error.HTTPError as exc:
            raise _OdooError(f"HTTP {exc.code}", terminal=not (500 <= exc.code < 600)) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise _OdooError(f"cannot reach Odoo: {exc}", terminal=False) from exc

        if parsed.get("error"):
            error = parsed["error"]
            message = (
                (error.get("data") or {}).get("message") or error.get("message") or "Odoo error"
            )
            raise _OdooError(str(message), terminal=True)
        return parsed.get("result")
