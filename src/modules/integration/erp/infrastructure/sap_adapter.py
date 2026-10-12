"""Real SAP adapter implementing the ErpAdapter port.

Targets SAP's public **Sales Order (A2X) API** (`API_SALES_ORDER_SRV`, OData V2) for
order submission/status, and the companion **Outbound Delivery** (`API_OUTBOUND_DELIVERY_SRV`)
and **Billing Document** (`API_BILLING_DOCUMENT_SRV`) APIs for shipments/invoices — all part
of SAP's standard S/4HANA public API surface (SAP API Business Hub).

Field correspondence (payload building + status reading) follows the human-reviewed
mapping below exactly — not re-derived here:

    SalesOrder              -> erp_order_id              (95%)
    PurchaseOrderByCustomer -> client_reference          (95%)
    Material                -> product_key               (95%)
    RequestedQuantity       -> quantity                  (95%)
    RequestedQuantityUnit   -> unit_of_measure            (95%)
    NetAmount               -> unit_price   (LOW CONFIDENCE, 40% — approved anyway; see the
                                comment at each call site below for why it's flagged)

Stdlib-only HTTP, explicit timeouts, transient/terminal error classification
(RESILIENCY-10) — same shape as `odoo_adapter.py`. Exercised against a live SAP system is
out of scope here; unit tests mock the HTTP seam (`_oauth_token`/`_do_request`), per
`test_sap_adapter.py`, not a live SAP.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
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


class _SapError(Exception):
    def __init__(self, message: str, *, terminal: bool) -> None:
        super().__init__(message)
        self.terminal = terminal


def build_sap_order_items(order_payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Pure: turn the ERP-neutral payload into the fields resolved into SAP sales-order
    items (`A_SalesOrderItem`). Mirrors `odoo_adapter.build_sale_order_lines`'s shape so
    it's unit-testable without a live server.

    Field correspondence per the approved mapping: `product_key` -> `Material`,
    `quantity` -> `RequestedQuantity`, `unit_of_measure` -> `RequestedQuantityUnit`,
    `unit_price` -> `NetAmount`.
    """
    items: list[dict[str, Any]] = []
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
        items.append(
            {
                # Material: approved mapping, direct passthrough — SAP's Material field
                # IS the material master's own key (unlike Odoo's product.product, which
                # needs an internal numeric id resolved via a lookup). An invalid/unknown
                # code is not resolved here; it fails closed naturally when SAP's own
                # OData validation rejects the create (surfaced as a terminal error by
                # `submit`, not silently auto-created).
                "product_key": product_key,
                "quantity": max(qty, 0.0) or 1.0,
                # RequestedQuantityUnit: approved mapping, direct passthrough — no name
                # lookup table was approved for this field, unlike Odoo's `uom.uom` search.
                "unit_of_measure": str(raw.get("unit_of_measure") or ""),
                # NetAmount: approved mapping, but LOW CONFIDENCE (40%) — SAP's NetAmount
                # is often the item's pricing-procedure-computed net value rather than a
                # literal per-unit price, and may be overridden by SAP's own condition
                # records on create regardless of what is sent here. Implemented exactly
                # as approved; flagged here for a human reviewer to double-check against
                # a real account before relying on it.
                "unit_price": net_unit_price,
                "currency": unit_price["currency"] if unit_price is not None else None,
            }
        )
    return items


class SapAdapter:
    # Declared per ADR-0015 (inspectable, not yet gated on). No `tax`/`uom`: the approved
    # mapping has no tax field, and `unit_of_measure`/`Material` are direct passthroughs
    # with no resolution lookup, unlike Odoo's `uom.uom`/`account.tax` searches.
    capabilities = frozenset({"idempotency", "fail_closed_product", "partial_fulfillment"})

    def __init__(self, timeout_seconds: float = 10.0) -> None:
        self._timeout = timeout_seconds

    # --- ErpAdapter port ---
    def submit(self, target: ErpTarget, order_payload: dict[str, Any]) -> SubmissionResult:
        try:
            token = self._oauth_token(target)
            order_id = order_payload.get("order_id")
            if order_id:
                # Idempotency (same reasoning as Odoo's client_order_ref): our own
                # platform order_id is written to PurchaseOrderByCustomer on create and
                # searched here first, so a retried submit returns the existing order
                # instead of duplicating. NOTE: this reuses the same field the approved
                # mapping targets for the *reseller's* client_reference when reading
                # orders we did not create ourselves (`fetch_partner_orders` below) — SAP's
                # PurchaseOrderByCustomer is a free-text "customer reference" slot playing
                # double duty here, exactly like Odoo's client_order_ref does for Odoo.
                # This dual use is our own adapter design (adding-an-erp.md's guidance to
                # copy Odoo's idempotency pattern), not part of the approved field mapping
                # itself.
                existing = self._request(
                    target,
                    token,
                    "GET",
                    "/A_SalesOrder",
                    params={
                        "$filter": f"PurchaseOrderByCustomer eq '{order_id}'",
                        "$format": "json",
                    },
                )
                results = (existing or {}).get("d", {}).get("results", [])
                if results:
                    return SubmissionResult(
                        success=True, erp_order_id=str(results[0]["SalesOrder"])
                    )

            sold_to_party = self._sold_to_party(order_payload)
            header = self._org_structure(target)
            items = [
                {
                    "Material": item["product_key"],
                    "RequestedQuantity": item["quantity"],
                    "RequestedQuantityUnit": item["unit_of_measure"],
                    **(
                        {"NetAmount": item["unit_price"]}
                        if item["unit_price"] is not None
                        else {}
                    ),
                }
                for item in build_sap_order_items(order_payload)
            ]
            body: dict[str, Any] = {
                "SoldToParty": sold_to_party,
                **header,
                # Deep insert: header + nested items in one POST — SAP OData V2's
                # standard create pattern for a sales order with its lines.
                "to_Item": {"results": items},
            }
            if order_id:
                body["PurchaseOrderByCustomer"] = str(order_id)
            created = self._request(target, token, "POST", "/A_SalesOrder", json_body=body)
            record = (created or {}).get("d", {})
            erp_order_id = str(record.get("SalesOrder") or "")
            if not erp_order_id:
                raise _SapError("SAP did not return a SalesOrder number", terminal=True)
            return SubmissionResult(success=True, erp_order_id=erp_order_id)
        except _SapError as exc:
            return SubmissionResult(success=False, error=str(exc), terminal=exc.terminal)

    def fetch_partner_orders(self, target: ErpTarget, partner_id: str) -> list[ErpPartnerOrder]:
        """Sales orders that already exist for this partner. We do not create them."""
        try:
            token = self._oauth_token(target)
            payload = self._request(
                target,
                token,
                "GET",
                "/A_SalesOrder",
                params={
                    "$filter": f"SoldToParty eq '{partner_id}'",
                    "$expand": "to_Item",
                    "$format": "json",
                },
            )
            orders = (payload or {}).get("d", {}).get("results", [])
            found: list[ErpPartnerOrder] = []
            for order in orders:
                name = str(order.get("SalesOrder") or "")
                if not name:
                    continue
                raw_items = (order.get("to_Item") or {}).get("results", [])
                currency = str(order.get("TransactionCurrency") or "USD") or "USD"
                lines: list[ErpPartnerOrderLine] = []
                for item in raw_items:
                    # Material -> product_key, RequestedQuantity -> quantity: approved
                    # mapping, direct reads.
                    code = str(item.get("Material") or "")
                    quantity = item.get("RequestedQuantity") or 0
                    if not code or not quantity:
                        continue
                    lines.append(
                        ErpPartnerOrderLine(
                            product_key=code,
                            quantity=str(quantity),
                            # NetAmount -> unit_price: approved, LOW CONFIDENCE (40%) —
                            # see `build_sap_order_items` for why. Read back as-is here too.
                            unit_price=str(item.get("NetAmount") or ""),
                            currency=currency,
                        )
                    )
                if not lines:
                    continue
                found.append(
                    ErpPartnerOrder(
                        erp_order_id=name,
                        # PurchaseOrderByCustomer -> client_reference: approved mapping.
                        # Falls back to the SAP order number if the customer never set
                        # their own PO reference, same graceful fallback Odoo uses.
                        client_reference=str(order.get("PurchaseOrderByCustomer") or name),
                        lines=tuple(lines),
                    )
                )
            return found
        except _SapError:
            return []

    def fetch_status(self, target: ErpTarget, erp_order_id: str) -> dict[str, str] | None:
        try:
            token = self._oauth_token(target)
            payload = self._request(
                target,
                token,
                "GET",
                f"/A_SalesOrder('{erp_order_id}')",
                params={
                    # ASSUMPTION, from SAP's public API_SALES_ORDER_SRV documentation, to
                    # be verified against this account's real $metadata: these three
                    # header fields mirror the classic SD document status concept
                    # (processing/billing/rejection status, historically
                    # VBUK-GBSTK/FKSTK/ABSTK) exposed on `A_SalesOrder` under these names
                    # in the public OData service. Not an account-specific unknown — this
                    # is a reasoned default from SAP's own documented API shape, not a
                    # blank placeholder.
                    "$select": (
                        "OverallSDProcessStatus,OverallSDDocumentRejectionSts,"
                        "OverallBillingStatus"
                    ),
                    "$format": "json",
                },
            )
            record = (payload or {}).get("d")
            if not record:
                return None
            return {
                "overall_sd_process_status": str(record.get("OverallSDProcessStatus") or ""),
                "overall_sd_document_rejection_status": str(
                    record.get("OverallSDDocumentRejectionSts") or ""
                ),
                "overall_billing_status": str(record.get("OverallBillingStatus") or ""),
            }
        except _SapError:
            return None

    def fetch_shipments(self, target: ErpTarget, erp_order_id: str) -> list[ErpShipment]:
        """Outbound deliveries referencing this sales order, read from SAP's public
        Outbound Delivery API (`API_OUTBOUND_DELIVERY_SRV`) — a separate OData service
        from the Sales Order one, so it needs its own service root."""
        delivery_service_url = target.credentials.get("outbound_delivery_service_url")
        if not delivery_service_url:
            # TODO: this account's SAP landscape exposes `API_OUTBOUND_DELIVERY_SRV` at
            # its own service root (varies by API gateway / landscape setup and cannot be
            # derived from the Sales Order service's base_url) — add
            # `outbound_delivery_service_url` to this connection's `credentials` once
            # known. Returning [] (no shipments found yet) rather than guessing a URL.
            return []
        try:
            token = self._oauth_token(target)
            payload = self._do_request(
                target,
                token,
                "GET",
                delivery_service_url.rstrip("/") + "/A_OutbDeliveryItem",
                params={
                    # ASSUMPTION from SAP's public Outbound Delivery API docs: items
                    # reference their originating sales order via `ReferenceSDDocument`.
                    "$filter": f"ReferenceSDDocument eq '{erp_order_id}'",
                    "$expand": "to_DeliveryDocumentHeader",
                    "$format": "json",
                },
            )
            raw_items = (payload or {}).get("d", {}).get("results", [])
            by_delivery: dict[str, list[ErpShipmentLine]] = {}
            for item in raw_items:
                header = item.get("to_DeliveryDocumentHeader") or {}
                # ASSUMPTION, from the same public docs: a goods-issue-posted delivery is
                # the SAP analogue of Odoo's "done" picking.
                if str(header.get("GoodsMovementStatus") or "") != "C":
                    continue
                delivery_id = str(item.get("DeliveryDocument") or "")
                code = str(item.get("Material") or "")
                quantity = item.get("ActualDeliveryQuantity") or 0
                if not delivery_id or not code or not quantity:
                    continue
                by_delivery.setdefault(delivery_id, []).append(
                    ErpShipmentLine(product_key=code, quantity=str(quantity))
                )
            return [
                ErpShipment(erp_shipment_id=delivery_id, lines=tuple(lines), proof_of_delivery=delivery_id)
                for delivery_id, lines in by_delivery.items()
            ]
        except _SapError:
            return []

    def fetch_invoices(self, target: ErpTarget, erp_order_id: str) -> list[ErpInvoice]:
        """Posted billing documents referencing this sales order, read from SAP's public
        Billing Document API (`API_BILLING_DOCUMENT_SRV`) — again its own service root."""
        billing_service_url = target.credentials.get("billing_document_service_url")
        if not billing_service_url:
            # TODO: this account's SAP landscape exposes `API_BILLING_DOCUMENT_SRV` at its
            # own service root (same reasoning as `outbound_delivery_service_url` above) —
            # add `billing_document_service_url` to this connection's `credentials` once
            # known. Returning [] rather than guessing a URL.
            return []
        try:
            token = self._oauth_token(target)
            payload = self._do_request(
                target,
                token,
                "GET",
                billing_service_url.rstrip("/") + "/A_BillingDocumentItem",
                params={
                    # ASSUMPTION from SAP's public Billing Document API docs: items
                    # reference their originating sales order via `ReferenceSDDocument`.
                    "$filter": f"ReferenceSDDocument eq '{erp_order_id}'",
                    "$expand": "to_BillingDocument",
                    "$format": "json",
                },
            )
            raw_items = (payload or {}).get("d", {}).get("results", [])
            by_invoice: dict[str, tuple[str, list[ErpShipmentLine]]] = {}
            for item in raw_items:
                header = item.get("to_BillingDocument") or {}
                # Credit memos are skipped — same reasoning as Odoo dropping
                # `out_refund` moves in `fetch_invoices`.
                if str(header.get("SDDocumentCategory") or "") == "O":  # credit memo
                    continue
                invoice_id = str(item.get("BillingDocument") or "")
                code = str(item.get("Material") or "")
                quantity = item.get("BillingQuantity") or 0
                if not invoice_id or not code or not quantity:
                    continue
                number, lines = by_invoice.get(invoice_id, (invoice_id, []))
                lines.append(ErpShipmentLine(product_key=code, quantity=str(quantity)))
                by_invoice[invoice_id] = (number, lines)
            return [
                ErpInvoice(erp_invoice_id=invoice_id, lines=tuple(lines), number=number)
                for invoice_id, (number, lines) in by_invoice.items()
            ]
        except _SapError:
            return []

    def cancel(self, target: ErpTarget, erp_order_id: str) -> SubmissionResult:
        """SAP has no single "cancel" action on a sales order the way Odoo's
        `action_cancel` does — a sales order is rejected by setting a rejection reason on
        every item (`ReasonForRejection` on `A_SalesOrderItem`)."""
        rejection_reason = target.credentials.get("rejection_reason_code")
        if not rejection_reason:
            # TODO: this account's SAP configuration defines its own rejection reason
            # codes (e.g. "08", "Z1" — configured per client/customer, not standard across
            # accounts) — add `rejection_reason_code` to this connection's `credentials`
            # once known. Never invent one; a wrong code posts a meaningless rejection
            # reason to a real SAP system.
            return SubmissionResult(
                success=False,
                error="no rejection_reason_code configured for this SAP connection",
                terminal=True,
            )
        try:
            token = self._oauth_token(target)
            payload = self._request(
                target,
                token,
                "GET",
                f"/A_SalesOrder('{erp_order_id}')",
                params={"$expand": "to_Item", "$format": "json"},
            )
            record = (payload or {}).get("d")
            if not record:
                return SubmissionResult(success=False, error="order not found", terminal=True)
            items = (record.get("to_Item") or {}).get("results", [])
            for item in items:
                self._request(
                    target,
                    token,
                    "PATCH",
                    "/A_SalesOrderItem(SalesOrder='{}',SalesOrderItem='{}')".format(
                        erp_order_id, item["SalesOrderItem"]
                    ),
                    json_body={"ReasonForRejection": rejection_reason},
                )
            return SubmissionResult(success=True, erp_order_id=erp_order_id)
        except _SapError as exc:
            return SubmissionResult(success=False, error=str(exc), terminal=exc.terminal)

    # --- payload-building helpers ---
    @staticmethod
    def _sold_to_party(order_payload: dict[str, Any]) -> str:
        """The order is placed AS the reseller's ERP customer (FR-A1), same fail-closed
        reasoning as Odoo's `_partner_id`: `SoldToParty` is SAP's standard field for the
        customer on a sales order (`API_SALES_ORDER_SRV`, public docs) — used directly
        from the verified binding's `erp_customer_id`, never a name-based auto-create."""
        raw = order_payload.get("erp_customer_id")
        if raw in (None, ""):
            raise _SapError(
                "no erp_customer_id on the order — the reseller is not linked to an ERP customer",
                terminal=True,
            )
        return str(raw)

    @staticmethod
    def _org_structure(target: ErpTarget) -> dict[str, str]:
        """SAP's mandatory sales-document organizational fields (sales org / distribution
        channel / division / document type) are configured per account — e.g. one account
        might use order type "OR" in sales org "1000", another something entirely
        different. There is no public default that is correct for a real account, so
        these are read from this connection's `credentials` and fail closed if absent,
        rather than inventing a plausible-looking value."""
        required = (
            "sales_order_type",
            "sales_organization",
            "distribution_channel",
            "organization_division",
        )
        missing = [key for key in required if not target.credentials.get(key)]
        if missing:
            # TODO: this account's real SAP org-structure values (sales_order_type,
            # sales_organization, distribution_channel, organization_division) are
            # unknown without that account's own SAP configuration/API docs — add them to
            # this connection's `credentials`. Never invented here.
            raise _SapError(
                f"SAP connection is missing required org-structure credentials: {missing}",
                terminal=True,
            )
        return {
            "SalesOrderType": target.credentials["sales_order_type"],
            "SalesOrganization": target.credentials["sales_organization"],
            "DistributionChannel": target.credentials["distribution_channel"],
            "OrganizationDivision": target.credentials["organization_division"],
        }

    # --- HTTP/OData plumbing ---
    def _oauth_token(self, target: ErpTarget) -> str:
        """OAuth 2.0 client-credentials grant — SAP's current recommended auth for
        service-to-service integration against S/4HANA Cloud / BTP-fronted systems
        (Communication Arrangements), per SAP's public API Business Hub documentation, in
        preference to legacy Basic Auth directly against the Gateway. ASSUMPTION: to be
        verified against this account's actual auth setup (an on-prem Gateway reached
        without a BTP front door might still only offer Basic Auth) before trusting in
        production.

        `credentials["client_id"]` + `target.secret` (the client secret, resolved via
        Secrets Manager — SECURITY-12) are the credential; `credentials["token_url"]`
        overrides the token endpoint, defaulting to `<base_url>/oauth/token` (the
        conventional XSUAA-style path) when not set.
        """
        client_id = target.credentials.get("client_id", "")
        token_url = (
            target.credentials.get("token_url") or target.base_url.rstrip("/") + "/oauth/token"
        )
        body = (
            f"grant_type=client_credentials&client_id={urllib.parse.quote(client_id)}"
            f"&client_secret={urllib.parse.quote(target.secret)}"
        ).encode("ascii")
        request = urllib.request.Request(
            token_url,
            data=body,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as response:
                parsed = json.loads(response.read())
        except urllib.error.HTTPError as exc:
            raise _SapError(
                f"HTTP {exc.code} from SAP OAuth token endpoint", terminal=True
            ) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise _SapError(f"cannot reach SAP OAuth token endpoint: {exc}", terminal=False) from exc
        token = parsed.get("access_token")
        if not token:
            raise _SapError("SAP OAuth token endpoint returned no access_token", terminal=True)
        return str(token)

    def _csrf_token(self, target: ErpTarget, bearer_token: str) -> tuple[str, str]:
        """SAP Gateway OData V2 services require a CSRF token (fetched via a GET with
        `X-CSRF-Token: Fetch`) on every state-changing call (POST/PUT/PATCH/DELETE) — a
        public, documented convention of the Gateway framework itself, not account-
        specific. Returns `(csrf_token, set-cookie header)` to replay on the mutating
        call."""
        request = urllib.request.Request(
            target.base_url.rstrip("/") + "/",
            headers={
                "X-CSRF-Token": "Fetch",
                "Accept": "application/json",
                "Authorization": f"Bearer {bearer_token}",
            },
            method="GET",
        )
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as response:
                token = str(response.headers.get("X-CSRF-Token") or "")
                cookie = str(response.headers.get("Set-Cookie") or "")
        except urllib.error.HTTPError as exc:
            raise _SapError(
                f"HTTP {exc.code} fetching CSRF token", terminal=not (500 <= exc.code < 600)
            ) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise _SapError(f"cannot reach SAP to fetch CSRF token: {exc}", terminal=False) from exc
        return token, cookie

    def _request(
        self,
        target: ErpTarget,
        bearer_token: str,
        method: str,
        path: str,
        *,
        params: dict[str, str] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        url = target.base_url.rstrip("/") + path
        return self._do_request(target, bearer_token, method, url, params=params, json_body=json_body)

    def _do_request(
        self,
        target: ErpTarget,
        bearer_token: str,
        method: str,
        url: str,
        *,
        params: dict[str, str] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        if params:
            url = f"{url}?{urllib.parse.urlencode(params)}"
        headers: dict[str, str] = {
            "Authorization": f"Bearer {bearer_token}",
            "Accept": "application/json",
        }
        data: bytes | None = None
        if method in ("POST", "PATCH", "PUT", "DELETE"):
            # CSRF token convention — see `_csrf_token`'s docstring.
            csrf_token, cookie = self._csrf_token(target, bearer_token)
            headers["X-CSRF-Token"] = csrf_token
            if cookie:
                headers["Cookie"] = cookie
        if json_body is not None:
            data = json.dumps(json_body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as response:
                raw = response.read()
                if not raw:
                    return None
                return json.loads(raw)  # type: ignore[no-any-return]
        except urllib.error.HTTPError as exc:
            # SAP OData error envelope: {"error": {"message": {"value": ...}, ...}} —
            # public, documented convention of the OData V2 protocol itself.
            message = f"HTTP {exc.code}"
            try:
                error_body = json.loads(exc.read())
                inner = (error_body.get("error") or {}).get("message") or {}
                detail = inner.get("value") if isinstance(inner, dict) else inner
                if detail:
                    message = f"HTTP {exc.code}: {detail}"
            except (ValueError, AttributeError):
                pass
            raise _SapError(message, terminal=not (500 <= exc.code < 600)) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise _SapError(f"cannot reach SAP: {exc}", terminal=False) from exc
