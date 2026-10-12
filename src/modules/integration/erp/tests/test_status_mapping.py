from __future__ import annotations

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


def test_sap_status_mapping() -> None:
    """Reads the 3-field bag `sap_adapter.fetch_status` returns — see `_map_sap`'s
    docstring for which SAP header fields these are an assumption about."""
    assert (
        map_native_status("SAP", {"overall_sd_process_status": "A"})
        is CanonicalStatus.CONFIRMED
    )
    assert (
        map_native_status("SAP", {"overall_sd_process_status": "C"})
        is CanonicalStatus.CONFIRMED
    )
    assert (
        map_native_status("SAP", {"overall_sd_document_rejection_status": "C"})
        is CanonicalStatus.CANCELLED
    )
    assert (
        map_native_status(
            "SAP",
            {"overall_sd_process_status": "C", "overall_billing_status": "C"},
        )
        is CanonicalStatus.CLOSED
    )
    # Rejection takes priority over a (contradictory) processing/billing status.
    assert (
        map_native_status(
            "SAP",
            {
                "overall_sd_document_rejection_status": "C",
                "overall_billing_status": "C",
            },
        )
        is CanonicalStatus.CANCELLED
    )
    assert map_native_status("SAP", {}) is None


def test_mapper_signature_is_a_field_bag_not_a_fixed_arity() -> None:
    """The generic signature must not force every ERP into Odoo's 2-field shape — a
    1-field ERP (just `status`) and an unused extra field must both be handled fine."""
    assert (
        map_native_status("ODOO", {"state": "sale", "unrelated_field": "whatever"})
        is CanonicalStatus.CONFIRMED
    )
    assert map_native_status("ODOO", {}) is None


def test_unregistered_erp_type_is_none_never_raises() -> None:
    """ERP_NEXT is currently unregistered (see STATUS_MAPPERS) — this is the behavior a
    new, not-yet-wired-up ERP type must have: safely ignored, not an error.
    Re-registering ERP_NEXT with its own mapper is the intended way to support it again;
    this test would then need ERP_NEXT's real expectations, like `test_odoo_status_mapping`
    has for Odoo and `test_sap_status_mapping` has for SAP."""
    assert map_native_status("ERP_NEXT", {"status": "Completed"}) is None
    assert map_native_status("ODOO", None) is None
    assert map_native_status("", {}) is None
