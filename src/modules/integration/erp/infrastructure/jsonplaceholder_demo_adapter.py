"""JSONPlaceholder Demo adapter implementing the ErpAdapter port.

JSONPlaceholder (https://jsonplaceholder.typicode.com) is a free, public fake REST API
("a free online REST API that you can use whenever you need some fake data" — its own
guide, https://jsonplaceholder.typicode.com/guide/). It is not a real ERP: it has no
concept of a sales order, a customer, a product line, a shipment, or an invoice. This
adapter exists to exercise this platform's own registration/delivery/reconciliation
pipeline end to end against a real, reachable, public HTTP API — not to represent a real
ERP integration.

Design choices below are split into exactly the two kinds the project asks every adapter
to be explicit about:

- Choices backed by JSONPlaceholder's own public documentation (its guide, linked above)
  are implemented as real, working defaults and labeled "ASSUMPTION (JSONPlaceholder
  public docs)" at the point they're made — a reasoned default, not a gap.
- Choices that depend on *this account's* own business semantics (which this adapter has
  no live account or account-specific docs to read) are left as explicit `TODO`
  comments naming exactly what's missing — never invented.

We stand "the sales order" in with a `/todos` record (fields: userId, id, title,
completed — per the public guide) because `completed` is the one boolean, status-like
field JSONPlaceholder's public schema exposes anywhere — see `status_mapping.py`'s
`_map_jsonplaceholder_demo`. `/posts` (fields: userId, id, title, body) has no such
field.

Stdlib-only HTTP client, explicit timeouts, and transient/terminal error classification
(RESILIENCY-10), same shape as `odoo_adapter.py`. Pure payload building
(`build_todo_payload`) is unit-testable without a server — see
`test_jsonplaceholder_demo_adapter.py` (mocks `_request`, never a live JSONPlaceholder).
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
    ErpShipment,
    ErpTarget,
    SubmissionResult,
)


class _JsonPlaceholderDemoError(Exception):
    def __init__(self, message: str, *, terminal: bool) -> None:
        super().__init__(message)
        self.terminal = terminal


def build_todo_payload(order_payload: dict[str, Any]) -> dict[str, Any]:
    """Pure: turn the ERP-neutral order payload into the body POSTed to `/todos`.
    `userId` (the resolved, fail-closed-checked ERP customer id) is deliberately NOT set
    here — see `_customer_id`/`submit`, mirroring Odoo's split between
    `build_sale_order_lines` (pure) and `_partner_id` (fail-closed, raises).

    Field choices, each labeled by where they came from:
    - `title`: platform `order_id` (the idempotency key, FR-A2). ASSUMPTION
      (JSONPlaceholder public docs): `title` is the one free-text field the `/todos`
      schema exposes, used the same way Odoo's `client_order_ref` is — our own
      reference, searched before create (see `submit`). TODO (account-specific): what
      this real account's own idempotency key actually is, if it differs, cannot be
      known without that account's own API docs.
    - `name`: canonical `parties.end_customer_name` -> ERP field `name`. Human-approved
      mapping, confidence 95% (see the mapping proposer) — implemented as given, not
      re-derived. Not part of JSONPlaceholder's documented `/todos` schema
      (title/completed/userId only); JSONPlaceholder's fake backend simply echoes back
      any extra key it is sent, so this rides along as an extra field.
    - `completed`: always `False` on create — a brand-new order has not reached the one
      "done" signal `/todos` exposes yet (see `status_mapping.py`).
    """
    order_id = order_payload.get("order_id") or ""
    parties = order_payload.get("parties") or {}
    end_customer_name = str(parties.get("end_customer_name") or "")
    payload: dict[str, Any] = {"title": str(order_id), "completed": False}
    if end_customer_name:
        # name -> end_customer_name (confidence 95%) — see docstring above.
        payload["name"] = end_customer_name
    return payload


class JsonPlaceholderDemoAdapter:
    # Declared per ADR-0015, deliberately empty: JSONPlaceholder's public schema has no
    # tax/uom/multi_currency concept at all (nothing to resolve, so no
    # `fail_closed_product` either — no product/line fields exist to resolve), and the
    # idempotency search below can't be trusted against a backend documented to never
    # actually persist what it's POSTed (see `submit`'s comment) — so `idempotency`
    # isn't claimed as a real guarantee here either.
    capabilities: frozenset[str] = frozenset()

    def __init__(self, timeout_seconds: float = 10.0) -> None:
        self._timeout = timeout_seconds

    # --- ErpAdapter port ---
    def submit(self, target: ErpTarget, order_payload: dict[str, Any]) -> SubmissionResult:
        try:
            order_id = order_payload.get("order_id")
            if order_id:
                # Idempotency check, same convention as Odoo's (search before create).
                # Known gap, not a TODO (this is documented behavior, not an unknown):
                # JSONPlaceholder's guide states writes are faked and never actually
                # persisted server-side, so a retried submit can never actually find the
                # row this search is looking for — kept anyway so the adapter's shape
                # matches every other ERP's, and so it's not silently missing if this is
                # ever pointed at a real, persisting account.
                existing = self._find_by_title(target, str(order_id))
                if existing is not None:
                    return SubmissionResult(success=True, erp_order_id=str(existing["id"]))
            customer_id = self._customer_id(order_payload)
            payload = build_todo_payload(order_payload)
            payload["userId"] = customer_id
            created = self._request(target, "POST", "/todos", payload)
            erp_order_id = str((created or {}).get("id") or "")
            if not erp_order_id:
                raise _JsonPlaceholderDemoError(
                    "JSONPlaceholder did not return an id for the created todo",
                    terminal=False,
                )
            return SubmissionResult(success=True, erp_order_id=erp_order_id)
        except _JsonPlaceholderDemoError as exc:
            return SubmissionResult(success=False, error=str(exc), terminal=exc.terminal)

    def fetch_partner_orders(self, target: ErpTarget, partner_id: str) -> list[ErpPartnerOrder]:
        """`/todos` filtered by `userId` stands in for "this partner's existing sales
        orders" — the closest the public API has to one (see `_customer_id`'s
        ASSUMPTION). Always returns `[]` today:

        TODO (account-specific): this account's own setup is the only place that could
        define which field(s) actually carry a line's `product_key`/`quantity`.
        JSONPlaceholder's public `/todos` schema has none at all (just
        id/title/completed/userId) — so every row fetched here has no line to build,
        and is filtered out below, same as every other adapter's "a line with no code
        is skipped" rule, just with nothing resolvable yet.
        """
        try:
            self._request(target, "GET", f"/todos?userId={urllib.parse.quote(str(partner_id))}")
        except _JsonPlaceholderDemoError:
            pass
        # Every row fetched above has no line to build (see the TODO above), so — same as
        # every other adapter's "a line with no code is skipped" rule, just with nothing
        # resolvable yet — none of them is adoptable. `ErpPartnerOrder` is still imported
        # for the port's return type, not constructed here.
        return []

    def fetch_status(self, target: ErpTarget, erp_order_id: str) -> dict[str, str] | None:
        try:
            row = self._request(target, "GET", f"/todos/{urllib.parse.quote(erp_order_id)}")
        except _JsonPlaceholderDemoError:
            return None
        if not row or row.get("id") is None:
            return None
        return {"completed": str(bool(row.get("completed"))).lower()}

    def fetch_shipments(self, target: ErpTarget, erp_order_id: str) -> list[ErpShipment]:
        """Verified from JSONPlaceholder's public guide (not a TODO): there is no
        delivery/shipment resource of any kind in its schema (posts, comments, albums,
        photos, todos, users — none of them). Always `[]`."""
        return []

    def fetch_invoices(self, target: ErpTarget, erp_order_id: str) -> list[ErpInvoice]:
        """Same as `fetch_shipments` — no invoice/billing resource exists in
        JSONPlaceholder's public schema either. Always `[]`."""
        return []

    def cancel(self, target: ErpTarget, erp_order_id: str) -> SubmissionResult:
        try:
            # ASSUMPTION (JSONPlaceholder public docs): DELETE is the documented verb for
            # removing a resource. Known gap, not a TODO: the same guide notes writes
            # (including deletes) are faked, so this never actually removes anything
            # server-side — kept so the adapter still reports success/failure correctly
            # if ever pointed at a real, persisting account.
            self._request(target, "DELETE", f"/todos/{urllib.parse.quote(erp_order_id)}")
            return SubmissionResult(success=True, erp_order_id=erp_order_id)
        except _JsonPlaceholderDemoError as exc:
            return SubmissionResult(success=False, error=str(exc), terminal=exc.terminal)

    # --- helpers ---
    def _find_by_title(self, target: ErpTarget, title: str) -> dict[str, Any] | None:
        try:
            rows = self._request(target, "GET", f"/todos?title={urllib.parse.quote(title)}")
        except _JsonPlaceholderDemoError:
            return None
        if isinstance(rows, list) and rows:
            return rows[0]
        return None

    @staticmethod
    def _customer_id(order_payload: dict[str, Any]) -> int:
        """ASSUMPTION (JSONPlaceholder public docs): every writable resource models
        ownership via `userId` — used here as where the order's resolved ERP customer id
        goes, since JSONPlaceholder has no sales-specific customer field at all. Fails
        closed on a missing/invalid id, same FR-A1 reasoning as Odoo's `_partner_id`
        (never a silent, nameless auto-created customer). TODO (account-specific): if the
        real account this demo eventually points at uses `userId` for something other
        than "the customer" (e.g. an internal rep), that can only be learned from that
        account's own docs, not from JSONPlaceholder's public guide."""
        raw = order_payload.get("erp_customer_id")
        if raw in (None, ""):
            raise _JsonPlaceholderDemoError(
                "no erp_customer_id on the order — the reseller is not linked to an ERP customer",
                terminal=True,
            )
        try:
            return int(raw)
        except (TypeError, ValueError) as exc:
            raise _JsonPlaceholderDemoError(
                f"erp_customer_id {raw!r} is not a valid JSONPlaceholder userId", terminal=True
            ) from exc

    def _request(
        self, target: ErpTarget, method: str, path: str, body: dict[str, Any] | None = None
    ) -> Any:
        # ASSUMPTION (JSONPlaceholder public docs, https://jsonplaceholder.typicode.com/
        # guide/): "free to use" with no signup/API key/auth of any kind — so no
        # Authorization header is sent. `target.secret`/`credentials` are accepted by the
        # `ErpAdapter` port but unused here. TODO (account-specific): if this demo is
        # ever pointed at a real account that *does* require auth, the actual scheme
        # (API key header? OAuth?) is that account's own detail, learned from its own
        # docs — not guessable from JSONPlaceholder's public ones.
        url = target.base_url.rstrip("/") + path
        data = json.dumps(body).encode("utf-8") if body is not None else None
        headers = {"Content-Type": "application/json"} if data is not None else {}
        request = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as response:
                raw = response.read()
        except urllib.error.HTTPError as exc:
            raise _JsonPlaceholderDemoError(
                f"HTTP {exc.code}", terminal=not (500 <= exc.code < 600)
            ) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise _JsonPlaceholderDemoError(
                f"cannot reach JSONPlaceholder Demo: {exc}", terminal=False
            ) from exc
        if not raw:
            return {}
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            raise _JsonPlaceholderDemoError(
                f"non-JSON response from JSONPlaceholder Demo: {exc}", terminal=False
            ) from exc
