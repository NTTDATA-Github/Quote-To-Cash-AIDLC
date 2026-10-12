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


def _map_sap(fields: dict[str, str]) -> CanonicalStatus | None:
    """Reads the three header fields `sap_adapter.fetch_status` returns.

    ASSUMPTION, from SAP's public `API_SALES_ORDER_SRV` documentation, to be verified
    against a real account's `$metadata` before trusting in production: these mirror the
    classic SD document status concept (processing / billing / rejection status,
    historically VBUK-GBSTK/FKSTK/ABSTK) that SAP's public OData API exposes on
    `A_SalesOrder` under the field names read in `sap_adapter.fetch_status`. Not an
    account-specific unknown — this is a reasoned default built from SAP's own
    documented API shape, not a guess at this account's own configuration.
    """
    rejection = fields.get("overall_sd_document_rejection_status", "")
    billing = fields.get("overall_billing_status", "")
    processing = fields.get("overall_sd_process_status", "")
    if rejection == "c":  # completely rejected
        return CanonicalStatus.CANCELLED
    if billing == "c":  # completely invoiced
        return CanonicalStatus.CLOSED
    if processing in ("a", "b", "c"):  # order exists and isn't fully rejected/invoiced
        return CanonicalStatus.CONFIRMED
    return None


# The one place a new ERP's status mapping is registered. Keyed by the same string an
# `ErpConnection.erp_type`/`ErpTarget.erp_type` carries (upper-cased).
STATUS_MAPPERS: dict[str, StatusMapper] = {
    "ODOO": _map_odoo,
    "SAP": _map_sap,
}


def map_native_status(erp_type: str, fields: dict[str, str] | None) -> CanonicalStatus | None:
    mapper = STATUS_MAPPERS.get((erp_type or "").upper())
    if mapper is None:
        return None
    clean = {k: (v or "").strip().lower() for k, v in (fields or {}).items()}
    return mapper(clean)
