"""Native-ERP-status -> canonical-status mapping, as a registry (a PBT target).

To add a new ERP's status mapping: write one pure function `(fields: dict[str, str]) ->
CanonicalStatus | None` that reads whatever keys that ERP's status actually arrives in.
The signature doesn't force an arity — Odoo reads 2 keys (`state`, `invoice_status`), a
single-status-string ERP reads 1 (`status`), a hypothetical 3-field ERP reads 3. Add one
line to `STATUS_MAPPERS`. No other file changes. `map_native_status` itself never needs to
change again — this replaced an earlier version that hardcoded exactly 2 positional
string arguments, which was Odoo's shape leaking into what was meant to be ERP-neutral.
"""

from __future__ import annotations

from collections.abc import Callable

# `CanonicalStatus` lives in `shared` now (ADR-0018) so `sales` can consume it without
# importing `integration`. Re-exported here so this module's own API is unchanged.
from src.shared.canonical_status import CanonicalStatus

__all__ = ["CanonicalStatus", "StatusMapper", "map_native_status", "STATUS_MAPPERS"]


# Inputs are already lowercased/stripped by `map_native_status` before the mapper sees them.
StatusMapper = Callable[[dict[str, str]], "CanonicalStatus | None"]


def _map_odoo(fields: dict[str, str]) -> CanonicalStatus | None:
    native = fields.get("state", "")
    invoice = fields.get("invoice_status", "")
    if native == "cancel":
        return CanonicalStatus.CANCELLED
    if invoice == "invoiced":
        return CanonicalStatus.CLOSED
    # Both "sale" (confirmed) and "done" (locked/fully delivered) map to CONFIRMED now —
    # delivery is tracked as a fact via Fulfillment records, not this status (FR-A6).
    if native in ("sale", "done"):
        return CanonicalStatus.CONFIRMED
    return None


def _map_jsonplaceholder_demo_erp(fields: dict[str, str]) -> CanonicalStatus | None:
    """JSONPlaceholder Demo ERP's public API (`/posts`, `/comments`, `/albums`,
    `/photos`, `/todos`, `/users`) has no order-lifecycle/status concept at all —
    nothing in its publicly documented schema plays the role of Odoo's `state` or
    ERPNext's `status`. `JsonPlaceholderDemoErpAdapter.fetch_status` reads whatever this
    *account's* own order record returns in a `status` key (see that adapter for the
    `GET /posts/{id}` call this comes from).

    TODO(account-specific, needs a live account or its API docs): the real field name
    this account's own schema uses for order status (if `status` is even right) and,
    more importantly, the actual value vocabulary (e.g. is "closed" spelled that way? is
    there a distinct cancelled value, or is a cancelled order just deleted?) are not
    knowable from JSONPlaceholder's public documentation — there is nothing to read
    them from. Never guess at those values: until a human fills this in from the real
    account, every status value maps to "no transition" rather than a made-up guess.
    """
    return None


# The one place a new ERP's status mapping is registered. Keyed by the same string an
# `ErpConnection.erp_type`/`ErpTarget.erp_type` carries (upper-cased).
STATUS_MAPPERS: dict[str, StatusMapper] = {
    "ODOO": _map_odoo,
    "JSONPLACEHOLDER_DEMO_ERP": _map_jsonplaceholder_demo_erp,
}


def map_native_status(erp_type: str, fields: dict[str, str] | None) -> CanonicalStatus | None:
    mapper = STATUS_MAPPERS.get((erp_type or "").upper())
    if mapper is None:
        return None
    clean = {k: (v or "").strip().lower() for k, v in (fields or {}).items()}
    return mapper(clean)
