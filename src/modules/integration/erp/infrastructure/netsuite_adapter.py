"""Real NetSuite adapter (SuiteTalk REST Web Services) implementing the ErpAdapter port.

Stdlib-only client with explicit timeouts and transient/terminal error classification
(RESILIENCY-10), the same shape as `odoo_adapter.py`. Talks the account-specific SuiteTalk
REST dialect (`/services/rest/record/v1/...` + `/services/rest/query/v1/suiteql`) and signs
every request with Token-Based Authentication (OAuth 1.0a, HMAC-SHA256 — NetSuite dropped
HMAC-SHA1 in 2023.1).

Pure request-shaping (`build_salesorder_lines`, `oauth1_authorization_header`,
`parse_record_id_from_location`) is unit-testable without a server. Exercised end-to-end
against the faithful in-process mock (`scripts/mock_netsuite.py`,
`tests/integration/test_netsuite_adapter_against_mock.py`); the same code path hits a live
NetSuite account by changing only `ErpTarget.base_url` + the resolved secret (plug-and-play).

Secret model (ADR-equivalent, see netsuite-integration-requirements.md D-NS-2): the single
`ErpTarget.secret` carries a JSON blob `{"consumer_secret": ..., "token_secret": ...}` — the
two *secret* TBA components — while the non-secret `account_id`/`consumer_key`/`token_id`
live in `ErpTarget.credentials`. This keeps NetSuite inside the existing one-secret
connection contract with no schema change. A malformed/empty secret is a terminal auth error.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import random
import time
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

_RECORD_PATH = "/services/rest/record/v1"
_SUITEQL_PATH = "/services/rest/query/v1/suiteql"


class _NetSuiteError(Exception):
    def __init__(self, message: str, *, terminal: bool) -> None:
        super().__init__(message)
        self.terminal = terminal


# --- pure helpers (no live server needed) ---
def _pct(value: str) -> str:
    """RFC 3986 percent-encoding for OAuth: encode everything except the unreserved set
    `A-Za-z0-9-._~` (urllib keeps those plus whatever is in `safe`; `safe=""` makes it
    also encode `/`, which OAuth requires)."""
    return urllib.parse.quote(str(value), safe="")


def oauth1_authorization_header(
    method: str,
    url: str,
    *,
    account_id: str,
    consumer_key: str,
    token_id: str,
    consumer_secret: str,
    token_secret: str,
    nonce: str,
    timestamp: str,
) -> str:
    """Build a NetSuite TBA `Authorization: OAuth ...` header. Deterministic given `nonce`
    and `timestamp`, so it is unit-testable. Query-string params in `url` are folded into
    the signature base string per the OAuth 1.0a spec; the JSON body is not signed."""
    split = urllib.parse.urlsplit(url)
    base_url = urllib.parse.urlunsplit((split.scheme, split.netloc, split.path, "", ""))
    oauth_params = {
        "oauth_consumer_key": consumer_key,
        "oauth_token": token_id,
        "oauth_signature_method": "HMAC-SHA256",
        "oauth_timestamp": timestamp,
        "oauth_nonce": nonce,
        "oauth_version": "1.0",
    }
    all_params = list(oauth_params.items()) + urllib.parse.parse_qsl(split.query)
    # OAuth 1.0a: sort the raw key/value pairs, then percent-encode once and join.
    normalized = "&".join(f"{_pct(k)}={_pct(v)}" for k, v in sorted(all_params))
    base_string = f"{method.upper()}&{_pct(base_url)}&{_pct(normalized)}"
    signing_key = f"{_pct(consumer_secret)}&{_pct(token_secret)}"
    signature = base64.b64encode(
        hmac.new(signing_key.encode("utf-8"), base_string.encode("utf-8"), hashlib.sha256).digest()
    ).decode("ascii")
    header_params = {
        **oauth_params,
        "oauth_signature": signature,
    }
    # realm is the account id, upper-cased (NetSuite requirement; sandbox is e.g. 1234567_SB1)
    parts = ", ".join(f'{k}="{_pct(v)}"' for k, v in header_params.items())
    return f'OAuth realm="{account_id.upper()}", {parts}'


def parse_record_id_from_location(location: str | None) -> str | None:
    """A record create returns `204 No Content` with a `Location` header ending in the new
    internal id — `.../services/rest/record/v1/salesOrder/12345`. Return that last segment."""
    if not location:
        return None
    segment = urllib.parse.urlsplit(location).path.rstrip("/").rsplit("/", 1)[-1]
    return segment or None


def build_salesorder_lines(order_payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Pure: ERP-neutral payload -> the fields we resolve into NetSuite salesOrder item
    lines. `unit_price`/`line_discount` are the JSON-safe `money.py` shapes
    (`{"amount": str, "currency": str}`); the net unit price (price minus any flat per-unit
    discount) becomes NetSuite's line `rate`. Resolving SKUs/tax codes into real ids happens
    in `submit`."""
    lines: list[dict[str, Any]] = []
    for raw in order_payload.get("lines", []) or []:
        product_key = str(raw.get("product_key") or "UNKNOWN")
        try:
            qty = float(raw.get("quantity", 0) or 0)
        except (TypeError, ValueError):
            qty = 0.0
        unit_price = raw.get("unit_price")
        line_discount = raw.get("line_discount")
        net_rate = None
        currency = None
        if unit_price is not None:
            price = float(unit_price["amount"])
            discount = float(line_discount["amount"]) if line_discount is not None else 0.0
            net_rate = max(price - discount, 0.0)
            currency = unit_price["currency"]
        lines.append(
            {
                "product_key": product_key,
                "quantity": max(qty, 0.0) or 1.0,
                "unit_of_measure": str(raw.get("unit_of_measure") or ""),
                "rate": net_rate,
                "currency": currency,
                "tax_codes": [t["code"] for t in (raw.get("tax_rates") or [])],
            }
        )
    return lines


def _sql_literal(value: str) -> str:
    """Single-quoted SuiteQL string literal with quotes doubled (SuiteQL uses standard SQL
    escaping). Only used for SKU/text values; numeric ids go through `_as_int`."""
    return "'" + str(value).replace("'", "''") + "'"


def _as_int(value: str) -> int | None:
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return None


class NetSuiteAdapter:
    # Declared per ADR-0015 (inspectable, not yet gated on). `partial_fulfillment` is the
    # itemFulfillment read in `fetch_shipments`. `multi_currency` absent: one currency assumed.
    capabilities = frozenset(
        {"tax", "uom", "idempotency", "fail_closed_product", "partial_fulfillment"}
    )

    def __init__(self, timeout_seconds: float = 10.0) -> None:
        self._timeout = timeout_seconds

    # --- ErpAdapter port ---
    def submit(self, target: ErpTarget, order_payload: dict[str, Any]) -> SubmissionResult:
        try:
            order_id = order_payload.get("order_id")
            # Idempotency key is the platform order id (FR-A2), written to NetSuite's
            # externalId on create and looked up here first so a retried submit (e.g. after
            # a timeout where the first attempt actually created the order) returns the
            # existing record instead of duplicating it.
            if order_id:
                status, _, body = self._request(
                    target, "GET", f"{_RECORD_PATH}/salesOrder/eid:{order_id}"
                )
                if status == 200 and body and body.get("id"):
                    return SubmissionResult(success=True, erp_order_id=str(body["id"]))
            customer_id = self._customer_id(order_payload)
            items: list[dict[str, Any]] = []
            for line in build_salesorder_lines(order_payload):
                item_id = self._resolve_item(target, line["product_key"])
                entry: dict[str, Any] = {
                    "item": {"id": item_id},
                    "quantity": line["quantity"],
                }
                if line["rate"] is not None:
                    # Net of any flat per-unit discount, already subtracted in
                    # build_salesorder_lines — NetSuite's own line `discount` is a separate
                    # concept, so we fold the flat discount into the rate.
                    entry["rate"] = line["rate"]
                units_id = self._resolve_unit(target, line["unit_of_measure"])
                if units_id is not None:
                    entry["units"] = {"id": units_id}
                tax_id = next(
                    (
                        resolved
                        for resolved in (
                            self._resolve_taxcode(target, code) for code in line["tax_codes"]
                        )
                        if resolved is not None
                    ),
                    None,
                )
                if tax_id is not None:
                    entry["taxCode"] = {"id": tax_id}
                items.append(entry)
            vals: dict[str, Any] = {"entity": {"id": customer_id}, "item": {"items": items}}
            if order_id:
                vals["externalId"] = str(order_id)
            _, headers, body = self._request(
                target, "POST", f"{_RECORD_PATH}/salesOrder", body=vals
            )
            internal_id = parse_record_id_from_location(headers.get("Location"))
            if internal_id is None and body:
                internal_id = str(body.get("id") or "") or None
            if internal_id is None:
                raise _NetSuiteError(
                    "salesOrder created but NetSuite returned no record id", terminal=True
                )
            return SubmissionResult(success=True, erp_order_id=internal_id)
        except _NetSuiteError as exc:
            return SubmissionResult(success=False, error=str(exc), terminal=exc.terminal)

    def fetch_status(self, target: ErpTarget, erp_order_id: str) -> dict[str, str] | None:
        try:
            status, _, body = self._request(
                target, "GET", f"{_RECORD_PATH}/salesOrder/{erp_order_id}"
            )
            if status == 404 or not body:
                return None
            return {
                "status": _ref_text(body.get("status")),
                "order_status": _ref_text(body.get("orderStatus")),
            }
        except _NetSuiteError:
            return None

    def fetch_partner_orders(self, target: ErpTarget, partner_id: str) -> list[ErpPartnerOrder]:
        """Sales orders that already exist for this customer. We do not create them."""
        pid = _as_int(partner_id)
        if pid is None:
            return []
        try:
            rows = self._suiteql(
                target,
                "SELECT id, tranid, externalid, subsidiary FROM transaction "
                f"WHERE type = 'SalesOrd' AND entity = {pid}",
            )
            found: list[ErpPartnerOrder] = []
            for row in rows:
                order_id = str(row.get("id") or "")
                if not order_id:
                    continue
                lines = [
                    ErpPartnerOrderLine(
                        product_key=raw["product_key"],
                        quantity=raw["quantity"],
                        unit_price="" if raw["rate"] is None else str(raw["rate"]),
                        currency="USD",
                    )
                    for raw in self._raw_lines(target, order_id)
                ]
                if not lines:
                    continue
                reference = str(row.get("externalid") or row.get("tranid") or order_id)
                found.append(
                    ErpPartnerOrder(
                        erp_order_id=order_id,
                        client_reference=reference,
                        lines=tuple(lines),
                        erp_company_id=str(row.get("subsidiary") or ""),
                    )
                )
            return found
        except _NetSuiteError:
            return []

    def fetch_shipments(self, target: ErpTarget, erp_order_id: str) -> list[ErpShipment]:
        """itemFulfillment documents created from this sales order. The fulfillment's
        `tranid` is the proof of delivery."""
        so_id = _as_int(erp_order_id)
        if so_id is None:
            return []
        try:
            fulfillments = self._suiteql(
                target,
                "SELECT id, tranid FROM transaction "
                f"WHERE type = 'ItemShip' AND createdfrom = {so_id}",
            )
            shipments: list[ErpShipment] = []
            for row in fulfillments:
                ship_id = str(row.get("id") or "")
                if not ship_id:
                    continue
                lines = [
                    ErpShipmentLine(product_key=raw["product_key"], quantity=raw["quantity"])
                    for raw in self._raw_lines(target, ship_id)
                ]
                if not lines:
                    continue
                shipments.append(
                    ErpShipment(
                        erp_shipment_id=ship_id,
                        lines=tuple(lines),
                        proof_of_delivery=str(row.get("tranid") or ship_id),
                    )
                )
            return shipments
        except _NetSuiteError:
            return []

    def fetch_invoices(self, target: ErpTarget, erp_order_id: str) -> list[ErpInvoice]:
        """Posted customer invoices created from this sales order."""
        so_id = _as_int(erp_order_id)
        if so_id is None:
            return []
        try:
            invoices_rows = self._suiteql(
                target,
                "SELECT id, tranid FROM transaction "
                f"WHERE type = 'CustInvc' AND createdfrom = {so_id}",
            )
            invoices: list[ErpInvoice] = []
            for row in invoices_rows:
                inv_id = str(row.get("id") or "")
                if not inv_id:
                    continue
                lines = [
                    ErpShipmentLine(product_key=raw["product_key"], quantity=raw["quantity"])
                    for raw in self._raw_lines(target, inv_id)
                ]
                if not lines:
                    continue
                invoices.append(
                    ErpInvoice(
                        erp_invoice_id=inv_id,
                        lines=tuple(lines),
                        number=str(row.get("tranid") or inv_id),
                    )
                )
            return invoices
        except _NetSuiteError:
            return []

    def cancel(self, target: ErpTarget, erp_order_id: str) -> SubmissionResult:
        """NetSuite has no first-class REST "cancel order" action — an unfulfilled sales
        order is cancelled by deleting it (a fulfilled one can't be, and returns an error we
        surface as terminal). A `404` means it is already gone, which we treat as success."""
        try:
            status, _, _ = self._request(
                target, "DELETE", f"{_RECORD_PATH}/salesOrder/{erp_order_id}"
            )
            if status in (200, 204, 404):
                return SubmissionResult(success=True, erp_order_id=erp_order_id)
            return SubmissionResult(
                success=False, error=f"unexpected status {status}", terminal=True
            )
        except _NetSuiteError as exc:
            return SubmissionResult(success=False, error=str(exc), terminal=exc.terminal)

    # --- resolution helpers (fail closed on product, graceful on tax/uom) ---
    def _resolve_item(self, target: ErpTarget, sku: str) -> str:
        """Fail closed, not silent auto-create: `routing.py` has already confirmed `sku` is
        a real SKU in *our* catalog. If NetSuite has no item with that `itemid`, that's
        catalog drift worth a human looking at — not a phantom item invented here."""
        rows = self._suiteql(target, f"SELECT id FROM item WHERE itemid = {_sql_literal(sku)}")
        if rows and rows[0].get("id"):
            return str(rows[0]["id"])
        raise _NetSuiteError(
            f"no NetSuite item with itemid '{sku}' — sync it in NetSuite before retrying",
            terminal=True,
        )

    def _resolve_unit(self, target: ErpTarget, name: str) -> str | None:
        """Graceful degradation (same reasoning as Odoo's `_resolve_uom`): an unmatched unit
        name falls back to the item's default unit rather than blocking the order."""
        if not name:
            return None
        rows = self._suiteql(
            target, f"SELECT id FROM unitstypeuom WHERE unitname = {_sql_literal(name)}"
        )
        return str(rows[0]["id"]) if rows and rows[0].get("id") else None

    def _resolve_taxcode(self, target: ErpTarget, code: str) -> str | None:
        """Graceful degradation: no matching NetSuite tax code means the line goes out
        without one, not a blocked order."""
        if not code:
            return None
        rows = self._suiteql(
            target, f"SELECT id FROM salestaxitem WHERE itemid = {_sql_literal(code)}"
        )
        return str(rows[0]["id"]) if rows and rows[0].get("id") else None

    def _raw_lines(self, target: ErpTarget, transaction_id: str) -> list[dict[str, Any]]:
        """Item lines of a transaction (sales order / fulfillment / invoice) as
        `{"product_key", "quantity"(abs, text), "rate"}`. Quantities are absolute (NetSuite
        stores outbound fulfillment lines negative). Callers build the right line dataclass
        (`ErpShipmentLine` has no price; `ErpPartnerOrderLine` carries the rate)."""
        tid = _as_int(transaction_id)
        if tid is None:
            return []
        rows = self._suiteql(
            target,
            "SELECT i.itemid AS itemid, tl.quantity AS quantity, tl.rate AS rate "
            f"FROM transactionline tl JOIN item i ON i.id = tl.item WHERE tl.transaction = {tid}",
        )
        lines: list[dict[str, Any]] = []
        for row in rows:
            code = str(row.get("itemid") or "")
            quantity = row.get("quantity")
            if not code or quantity in (None, "", 0):
                continue
            try:
                qty = abs(float(quantity))
            except (TypeError, ValueError):
                continue
            if qty == 0:
                continue
            lines.append({"product_key": code, "quantity": _num(qty), "rate": row.get("rate")})
        return lines

    @staticmethod
    def _customer_id(order_payload: dict[str, Any]) -> str:
        """The order is placed AS the reseller's NetSuite customer (FR-A1): `erp_customer_id`
        is NetSuite's own customer internal id, from the verified binding. A missing/invalid
        id is terminal, never a nameless auto-created customer."""
        raw = order_payload.get("erp_customer_id")
        if raw in (None, ""):
            raise _NetSuiteError(
                "no erp_customer_id on the order — the reseller is not linked to a "
                "NetSuite customer",
                terminal=True,
            )
        if _as_int(raw) is None:
            raise _NetSuiteError(
                f"erp_customer_id {raw!r} is not a valid NetSuite customer id", terminal=True
            )
        return str(raw)

    # --- SuiteTalk REST / OAuth plumbing ---
    def _credentials(self, target: ErpTarget) -> tuple[str, str, str, str, str]:
        account_id = target.credentials.get("account_id", "")
        consumer_key = target.credentials.get("consumer_key", "")
        token_id = target.credentials.get("token_id", "")
        try:
            secret = json.loads(target.secret) if target.secret else {}
            consumer_secret = str(secret["consumer_secret"])
            token_secret = str(secret["token_secret"])
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            raise _NetSuiteError(
                "NetSuite secret must be JSON with consumer_secret and token_secret",
                terminal=True,
            ) from exc
        if not (account_id and consumer_key and token_id):
            raise _NetSuiteError(
                "NetSuite credentials must include account_id, consumer_key and token_id",
                terminal=True,
            )
        return account_id, consumer_key, token_id, consumer_secret, token_secret

    def _suiteql(self, target: ErpTarget, query: str) -> list[dict[str, Any]]:
        status, _, body = self._request(
            target,
            "POST",
            _SUITEQL_PATH,
            body={"q": query},
            extra_headers={"Prefer": "transient"},
        )
        if status == 404 or not body:
            return []
        items = body.get("items")
        return list(items) if isinstance(items, list) else []

    def _request(
        self,
        target: ErpTarget,
        method: str,
        path: str,
        *,
        body: dict[str, Any] | None = None,
        extra_headers: dict[str, str] | None = None,
    ) -> tuple[int, dict[str, str], dict[str, Any] | None]:
        account_id, consumer_key, token_id, consumer_secret, token_secret = self._credentials(
            target
        )
        url = target.base_url.rstrip("/") + path
        authorization = oauth1_authorization_header(
            method,
            url,
            account_id=account_id,
            consumer_key=consumer_key,
            token_id=token_id,
            consumer_secret=consumer_secret,
            token_secret=token_secret,
            nonce="".join(random.choices("abcdefghijklmnopqrstuvwxyz0123456789", k=20)),
            timestamp=str(int(time.time())),
        )
        headers = {"Authorization": authorization, "Content-Type": "application/json"}
        if extra_headers:
            headers.update(extra_headers)
        data = json.dumps(body).encode("utf-8") if body is not None else None
        request = urllib.request.Request(url, data=data, headers=headers, method=method.upper())
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as response:
                raw = response.read()
                parsed = json.loads(raw) if raw else None
                return response.status, dict(response.headers), parsed
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return 404, dict(exc.headers or {}), None
            raw = exc.read()
            message = _error_message(raw) or f"HTTP {exc.code}"
            # 4xx (validation/auth) = terminal; 429 + 5xx = transient (retry via redrive).
            terminal = not (exc.code == 429 or 500 <= exc.code < 600)
            raise _NetSuiteError(message, terminal=terminal) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise _NetSuiteError(f"cannot reach NetSuite: {exc}", terminal=False) from exc


def _ref_text(value: Any) -> str:
    """A NetSuite status field can arrive as a plain string ("Pending Fulfillment") or as a
    `{id, refName}` object — return the human text either way, for the status mapper."""
    if isinstance(value, dict):
        return str(value.get("refName") or value.get("id") or "")
    return str(value or "")


def _num(value: float) -> str:
    """Decimal-as-text matching the shipment event shape: drop a trailing `.0`."""
    return f"{value:g}"


def _error_message(raw: bytes) -> str | None:
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return None
    details = parsed.get("o:errorDetails") if isinstance(parsed, dict) else None
    if isinstance(details, list) and details:
        detail = details[0]
        if isinstance(detail, dict) and detail.get("detail"):
            return str(detail["detail"])
    if isinstance(parsed, dict) and parsed.get("title"):
        return str(parsed["title"])
    return None
