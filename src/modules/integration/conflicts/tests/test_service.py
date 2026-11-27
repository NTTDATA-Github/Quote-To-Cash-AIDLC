from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from src.modules.integration.conflicts.application.service import (
    DELIVERED_ON_RETRY,
    SLA,
    ConflictService,
)
from src.modules.integration.conflicts.domain.categories import ConflictCategory
from src.modules.integration.conflicts.domain.models import (
    ConflictNotFound,
    ConflictStatus,
    Severity,
)
from src.modules.integration.conflicts.infrastructure.memory import InMemoryConflictRepository

NOW = datetime(2026, 10, 26, 9, 0, tzinfo=UTC)


def _service() -> ConflictService:
    return ConflictService(InMemoryConflictRepository(), clock=lambda: NOW)


def _fail(
    svc: ConflictService, order_id: str = "ord_1", *, terminal: bool = True, reason: str = "x"
):
    return svc.record_failure(
        tenant_id="tnt_demo",
        order_id=order_id,
        reason_code="erp_rejected" if terminal else "erp_unavailable",
        reason=reason,
        terminal=terminal,
    )


def test_a_rejected_delivery_opens_a_high_severity_conflict_with_an_sla() -> None:
    svc = _service()
    conflict = _fail(svc, reason="customer on hold")

    assert conflict.status is ConflictStatus.OPEN
    assert conflict.severity is Severity.HIGH
    assert conflict.attempts == 1
    assert conflict.opened_at == NOW
    assert conflict.sla_due_at == NOW + SLA
    assert conflict.reason == "customer on hold"


def test_a_transient_failure_is_medium_severity() -> None:
    svc = _service()
    conflict = _fail(svc, terminal=False)
    assert conflict.severity is Severity.MEDIUM


def test_repeated_failures_for_one_order_update_the_same_conflict() -> None:
    svc = _service()
    first = _fail(svc, terminal=False, reason="timeout")
    second = _fail(svc, terminal=False, reason="timeout again")

    assert second.conflict_id == first.conflict_id
    assert second.attempts == 2


def test_category_is_computed_once_at_record_time_not_left_null() -> None:
    """Regression test for the read-path cache this replaced: category used to be
    computed live on every GraphQL read; now it's set once, here, when the conflict
    is recorded, so a read never needs to classify anything itself."""
    svc = _service()
    conflict = _fail(svc, reason="customer on hold")

    assert conflict.category == "CUSTOMER_ON_HOLD"
    assert conflict.category_source == "RULE"


def test_a_message_no_rule_recognises_asks_the_injected_classifier() -> None:
    class _FixedClassifier:
        def classify(self, message: str) -> ConflictCategory | None:
            return ConflictCategory.ADDRESS_PROBLEM

    svc = ConflictService(
        InMemoryConflictRepository(), clock=lambda: NOW, classifier=_FixedClassifier()
    )
    conflict = _fail(svc, reason="0x4F2 unexpected")

    assert conflict.category == "ADDRESS_PROBLEM"
    assert conflict.category_source == "AI"


def test_with_no_classifier_injected_an_unrecognised_message_stays_unrecognised() -> None:
    """The default (no classifier passed) is UnavailableCauseClassifier, same as the
    GraphQL layer falls back to today — never a crash, never a silent guess."""
    svc = _service()
    conflict = _fail(svc, reason="0x4F2 unexpected")

    assert conflict.category == "OTHER"
    assert conflict.category_source == "UNRECOGNISED"


def test_category_is_recomputed_on_a_later_failure_with_a_different_reason() -> None:
    # terminal=False forces reason_code="erp_unavailable" (see _fail), and classify()
    # matches against "{reason_code} {reason}" combined - "unavailable" in the reason
    # code alone would always win ERP_UNREACHABLE regardless of `reason`, so both
    # failures here must be terminal to actually let `reason` drive the category.
    svc = _service()
    first = _fail(svc, terminal=True, reason="unknown item SKU-9")
    assert first.category == "PRODUCT_NOT_FOUND"

    second = _fail(svc, terminal=True, reason="customer on hold")
    assert second.category == "CUSTOMER_ON_HOLD"


def test_a_later_rejection_raises_the_severity_of_the_open_conflict() -> None:
    svc = _service()
    _fail(svc, terminal=False)
    conflict = _fail(svc, terminal=True)
    assert conflict.severity is Severity.HIGH


def test_a_closed_conflict_is_history_and_the_next_failure_opens_a_new_one() -> None:
    svc = _service()
    old = _fail(svc)
    svc.close_for_order("ord_1")

    new = _fail(svc)

    assert new.conflict_id != old.conflict_id
    assert new.status is ConflictStatus.OPEN
    assert svc.get(old.conflict_id).status is ConflictStatus.RESOLVED


def test_delivery_succeeding_on_retry_closes_the_open_conflict() -> None:
    svc = _service()
    _fail(svc, terminal=False)

    closed = svc.close_for_order("ord_1")

    assert closed is not None
    assert closed.status is ConflictStatus.RESOLVED
    assert closed.resolution_note == DELIVERED_ON_RETRY
    assert closed.resolved_at == NOW


def test_closing_an_order_with_nothing_open_is_a_no_op() -> None:
    svc = _service()
    assert svc.close_for_order("ord_never_failed") is None


def test_list_filters_by_status_and_get_rejects_an_unknown_id() -> None:
    svc = _service()
    _fail(svc, order_id="ord_1")
    _fail(svc, order_id="ord_2")
    svc.close_for_order("ord_2")

    assert {c.order_id for c in svc.list(ConflictStatus.OPEN)} == {"ord_1"}
    assert len(svc.list()) == 2
    with pytest.raises(ConflictNotFound):
        svc.get("cnf_missing")


def test_sla_deadline_is_the_opening_time_plus_the_sla() -> None:
    assert timedelta(hours=8) == SLA


def test_severity_comes_from_the_cause_and_whether_the_erp_refused() -> None:
    svc = _service()
    duplicate = svc.record_failure(
        tenant_id="tnt_demo",
        order_id="ord_dup",
        reason_code="erp_rejected",
        reason="Order already exists in the ERP",
        terminal=True,
    )
    on_hold = svc.record_failure(
        tenant_id="tnt_demo",
        order_id="ord_hold",
        reason_code="erp_rejected",
        reason="Customer on hold in the ERP",
        terminal=True,
    )
    assert duplicate.severity is Severity.LOW
    assert on_hold.severity is Severity.HIGH


def test_a_retrying_failure_uses_the_retrying_side_of_the_rule() -> None:
    svc = _service()
    conflict = svc.record_failure(
        tenant_id="tnt_demo",
        order_id="ord_dup",
        reason_code="erp_rejected",
        reason="Order already exists in the ERP",
        terminal=False,
    )
    assert conflict.severity is Severity.LOW


def test_a_changed_rule_applies_to_conflicts_opened_after_the_change() -> None:
    svc = _service()
    svc.set_severity_rule("PRICE_MISMATCH", when_rejected="HIGH", when_retrying="LOW")
    conflict = svc.record_failure(
        tenant_id="tnt_demo",
        order_id="ord_price",
        reason_code="erp_rejected",
        reason="Unit price differs from the price list",
        terminal=True,
    )
    assert conflict.severity is Severity.HIGH
    assert {r.category: r.when_rejected for r in svc.severity_rules()}[
        "PRICE_MISMATCH"
    ] is Severity.HIGH


def test_a_rule_rejects_an_unknown_cause_or_severity() -> None:
    svc = _service()
    with pytest.raises(ValueError, match="unknown cause"):
        svc.set_severity_rule("NOT_A_CAUSE", when_rejected="HIGH", when_retrying="LOW")
    with pytest.raises(ValueError, match="unknown severity"):
        svc.set_severity_rule("OTHER", when_rejected="URGENT", when_retrying="LOW")
