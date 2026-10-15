"""Builds the canonical order field list straight from the real domain model, instead of
a hand-typed CSV an operator must keep in sync by hand.

The fields a generated adapter actually has to populate from an ERP's raw data are
`ErpPartnerOrder`/`ErpPartnerOrderLine`/`ErpShipment`/`ErpShipmentLine`/`ErpInvoice` in
`integration.erp.application.ports` — that's the real contract, not a copy of it. Every
dataclass field on those becomes one row here via reflection; add a field there and it
shows up here on the very next request, no file to edit, nothing to keep in sync.
"""

from __future__ import annotations

import dataclasses

from src.modules.integration.erp.application.ports import (
    ErpInvoice,
    ErpPartnerOrder,
    ErpPartnerOrderLine,
    ErpShipment,
    ErpShipmentLine,
)

# Order matters only for a stable, readable CSV — order-level facts first, then the line
# items and the shipment/invoice facts that round out fulfillment and billing.
_SOURCE_DATACLASSES = (
    ErpPartnerOrder,
    ErpPartnerOrderLine,
    ErpShipment,
    ErpShipmentLine,
    ErpInvoice,
)
# A nested record (e.g. ErpPartnerOrder.lines: tuple[ErpPartnerOrderLine, ...]), not a
# flat field in its own right — its own dataclass is walked separately, above.
_SKIP_FIELDS = {"lines"}
_WORD_OVERRIDES = {"erp": "ERP", "id": "ID"}


def _humanize(field_name: str) -> str:
    words = [_WORD_OVERRIDES.get(w, w.capitalize()) for w in field_name.split("_")]
    return " ".join(words)


def build_canonical_order_fields() -> list[tuple[str, str]]:
    """One (field, description) pair per unique field name across all five dataclasses,
    first-seen order. Two dataclasses sharing a field name (e.g. `quantity` on both order
    and shipment lines) collapse to a single row — same concept, not two."""
    seen: dict[str, str] = {}
    for dc in _SOURCE_DATACLASSES:
        for f in dataclasses.fields(dc):
            if f.name in _SKIP_FIELDS or f.name in seen:
                continue
            seen[f.name] = _humanize(f.name)
    return list(seen.items())


def build_canonical_order_fields_csv() -> str:
    lines = ["field,description"]
    lines.extend(f"{name},{description}" for name, description in build_canonical_order_fields())
    return "\n".join(lines) + "\n"
