from __future__ import annotations

import pytest

from src.modules.integration.erp.domain.status_mapping import CanonicalStatus, map_native_status


def test_odoo_status_mapping() -> None:
    assert map_native_status("ODOO", {"state": "sale"}) is CanonicalStatus.CONFIRMED
    # "done" (fully delivered) now maps to CONFIRMED — delivery is a fact, not a lifecycle
    # status (FR-A6); FULFILLED left the lifecycle entirely.
    assert map_native_status("ODOO", {"state": "done"}) is CanonicalStatus.CONFIRMED
    assert map_native_status("ODOO", {"state": "cancel"}) is CanonicalStatus.CANCELLED
    assert (
        map_native_status("ODOO", {"state": "sale", "invoice_status": "invoiced"})
        is CanonicalStatus.CLOSED
    )
    assert map_native_status("ODOO", {"state": "draft"}) is None


def test_mapper_signature_is_a_field_bag_not_a_fixed_arity() -> None:
    """The generic signature must not force every ERP into Odoo's 2-field shape — a
    1-field ERP (just `status`) and an unused extra field must both be handled fine."""
    assert (
        map_native_status("ODOO", {"state": "sale", "unrelated_field": "whatever"})
        is CanonicalStatus.CONFIRMED
    )
    assert map_native_status("ODOO", {}) is None


def test_unregistered_erp_type_is_none_never_raises() -> None:
    """ERP_NEXT and SAP are both currently unregistered (see STATUS_MAPPERS) — this is
    the behavior a new, not-yet-wired-up ERP type must have: safely ignored, not an
    error. Re-registering ERP_NEXT with its own mapper is the intended way to support it
    again; this test would then need ERP_NEXT's real expectations, like
    `test_odoo_status_mapping` has for Odoo."""
    assert map_native_status("ERP_NEXT", {"status": "Completed"}) is None
    assert map_native_status("SAP", {"order_status": "whatever"}) is None
    assert map_native_status("ODOO", None) is None
    assert map_native_status("", {}) is None


def test_netsuite_status_mapping() -> None:
    """NetSuite reads the human `status` refName (and `order_status` code as fallback).
    map_native_status lowercases/strips before the mapper sees it."""
    ns = "NETSUITE"
    assert map_native_status(ns, {"status": "Pending Fulfillment"}) is CanonicalStatus.CONFIRMED
    assert map_native_status(ns, {"status": "Partially Fulfilled"}) is CanonicalStatus.CONFIRMED
    assert map_native_status(ns, {"status": "Pending Billing"}) is CanonicalStatus.CONFIRMED
    assert (
        map_native_status(ns, {"status": "Pending Billing/Partially Fulfilled"})
        is CanonicalStatus.CONFIRMED
    )
    assert map_native_status(ns, {"status": "Billed"}) is CanonicalStatus.CLOSED
    assert map_native_status(ns, {"status": "Closed"}) is CanonicalStatus.CLOSED
    assert map_native_status(ns, {"status": "Cancelled"}) is CanonicalStatus.CANCELLED
    # Canadian/US spelling and the coded fallback both resolve to CANCELLED.
    assert map_native_status(ns, {"status": "Canceled"}) is CanonicalStatus.CANCELLED
    assert map_native_status(ns, {"order_status": "C"}) is CanonicalStatus.CANCELLED
    # Pending Approval exists but isn't confirmed yet -> no transition.
    assert map_native_status(ns, {"status": "Pending Approval"}) is None
    assert map_native_status(ns, {}) is None


def test_netsuite_status_mapper_never_raises_on_arbitrary_fields() -> None:
    """PBT (extension: partial — pure functions). The mapper must tolerate any field bag:
    never raise, and return None for anything it doesn't recognize."""
    hypothesis = pytest.importorskip("hypothesis")
    from hypothesis import strategies as st

    text = st.text(max_size=40)

    @hypothesis.given(st.dictionaries(text, text, max_size=6))
    def _property(fields: dict[str, str]) -> None:
        result = map_native_status("NETSUITE", fields)
        assert result is None or isinstance(result, CanonicalStatus)

    _property()
