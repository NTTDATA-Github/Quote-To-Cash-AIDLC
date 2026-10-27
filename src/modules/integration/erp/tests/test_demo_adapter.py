from __future__ import annotations

from typing import Any

from src.modules.integration.erp.application.ports import ErpTarget, SubmissionResult
from src.modules.integration.erp.infrastructure.demo_adapter import (
    DEMO_REJECTION,
    DemoRejectingAdapter,
)

TARGET = ErpTarget(erp_type="ODOO", base_url="http://odoo", credentials={}, secret="x")


class _Inner:
    def __init__(self) -> None:
        self.submitted: list[dict[str, Any]] = []

    def submit(self, target: ErpTarget, order_payload: dict[str, Any]) -> SubmissionResult:
        self.submitted.append(order_payload)
        return SubmissionResult(success=True, erp_order_id="S1")


def test_an_order_for_a_listed_customer_is_rejected_as_terminal() -> None:
    inner = _Inner()
    adapter = DemoRejectingAdapter(inner, frozenset({"1"}))

    result = adapter.submit(TARGET, {"erp_customer_id": "1"})

    assert result.success is False
    assert result.terminal is True
    assert result.error == DEMO_REJECTION
    assert inner.submitted == []  # never reached the stub


def test_every_other_order_passes_through_to_the_stub() -> None:
    inner = _Inner()
    adapter = DemoRejectingAdapter(inner, frozenset({"1"}))

    result = adapter.submit(TARGET, {"erp_customer_id": "2"})

    assert result.success is True
    assert inner.submitted == [{"erp_customer_id": "2"}]
