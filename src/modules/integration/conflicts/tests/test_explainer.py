from __future__ import annotations

from datetime import UTC, datetime

import pytest

from src.modules.integration.conflicts.domain.models import (
    ConflictExplanationUnavailable,
    ConflictStatus,
    OrderConflict,
    Severity,
)
from src.modules.integration.conflicts.infrastructure.llm_explainer import (
    LlmConflictExplainer,
    UnavailableConflictExplainer,
)


def _conflict(attempts: int = 1, reason: str = "customer on hold") -> OrderConflict:
    now = datetime(2026, 10, 26, 9, 0, tzinfo=UTC)
    return OrderConflict(
        conflict_id="cnf_1",
        tenant_id="tnt_exn",
        order_id="ord_1",
        reason_code="erp_rejected",
        reason=reason,
        severity=Severity.HIGH,
        status=ConflictStatus.OPEN,
        attempts=attempts,
        assigned_to=None,
        resolution=None,
        resolution_note="",
        opened_at=now,
        sla_due_at=now,
        resolved_at=None,
    )


class FakeClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def ask(self, system: str, user: str, max_tokens: int = 0) -> str:
        self.calls.append((system, user))
        return "  The ERP has the customer on hold, so it refused the order.  "


def test_summary_is_built_from_the_conflict_facts_and_trimmed() -> None:
    client = FakeClient()
    text = LlmConflictExplainer(lambda: client).explain(_conflict(), "EXN")

    assert text == "The ERP has the customer on hold, so it refused the order."
    system, user = client.calls[0]
    assert "Use only the facts" in system
    assert "Reseller: EXN" in user
    assert "What happened: customer on hold" in user
    assert "Delivery attempts so far: 1" in user


def test_the_same_conflict_is_not_sent_to_the_model_twice() -> None:
    client = FakeClient()
    explainer = LlmConflictExplainer(lambda: client)
    explainer.explain(_conflict(), "EXN")
    explainer.explain(_conflict(), "EXN")
    assert len(client.calls) == 1


def test_a_new_attempt_gets_a_fresh_summary() -> None:
    client = FakeClient()
    explainer = LlmConflictExplainer(lambda: client)
    explainer.explain(_conflict(attempts=1), "EXN")
    explainer.explain(_conflict(attempts=2), "EXN")
    assert len(client.calls) == 2


def test_the_client_is_built_only_when_a_summary_is_first_asked_for() -> None:
    built: list[FakeClient] = []

    def factory() -> FakeClient:
        built.append(FakeClient())
        return built[-1]

    explainer = LlmConflictExplainer(factory)
    assert built == []
    explainer.explain(_conflict(), "EXN")
    assert len(built) == 1


def test_a_changed_reseller_name_gets_a_fresh_summary() -> None:
    """Regression test: the cache used to be keyed on (conflict_id, attempts, reason)
    only, so a reseller rename between two views of the same conflict silently kept
    serving the old reseller's name in the summary. Now keyed on the rendered facts
    themselves, which include the reseller name."""
    client = FakeClient()
    explainer = LlmConflictExplainer(lambda: client)
    explainer.explain(_conflict(), "EXN")
    explainer.explain(_conflict(), "EXN (renamed)")
    assert len(client.calls) == 2


def test_a_changed_severity_gets_a_fresh_summary() -> None:
    """Same regression, for severity: HIGH vs MEDIUM renders a different sentence in
    _facts() ("the ERP rejected the order" vs "delivery is still being retried"), which
    the old (conflict_id, attempts, reason)-only key couldn't see."""
    client = FakeClient()
    explainer = LlmConflictExplainer(lambda: client)
    high = _conflict()
    medium = _conflict()
    medium.severity = Severity.MEDIUM
    explainer.explain(high, "EXN")
    explainer.explain(medium, "EXN")
    assert len(client.calls) == 2


def test_a_transient_failure_recovers_on_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("src.shared.llm.client.time.sleep", lambda _seconds: None)

    class _FailsOnceThenWorks:
        def __init__(self) -> None:
            self.calls = 0

        def ask(self, system: str, user: str, max_tokens: int = 0) -> str:
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("transient DNS failure")
            return "Recovered summary."

    client = _FailsOnceThenWorks()
    text = LlmConflictExplainer(lambda: client).explain(_conflict(), "EXN")

    assert text == "Recovered summary."
    assert client.calls == 2


def test_without_a_provider_the_summary_says_why_it_is_unavailable() -> None:
    with pytest.raises(ConflictExplanationUnavailable, match="LLM_PROVIDER"):
        UnavailableConflictExplainer().explain(_conflict(), "EXN")
