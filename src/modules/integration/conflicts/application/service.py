"""ConflictService: records order conflicts and reads them for the operator queue.

View-only for now: nothing here changes an order or an ERP record. An operator can't resolve a
conflict yet; the only closing path is the system, when a later delivery of the same order
succeeds.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from src.shared.types import generate_id

from ..domain.categories import classify
from ..domain.models import (
    OPEN_STATUSES,
    ConflictNotFound,
    ConflictStatus,
    OpenConflictExists,
    OrderConflict,
    Severity,
    SeverityRule,
)
from ..infrastructure.llm_classifier import UnavailableCauseClassifier
from ..infrastructure.memory import InMemorySeverityRules
from .causes import cause_of

if TYPE_CHECKING:
    from collections.abc import Callable

    from .ports import CauseClassifier, ConflictRepository, SeverityRuleRepository

# How long an operator has to look at a conflict before it counts as overdue.
SLA = timedelta(hours=8)

# A conflict closed by the system, not by an operator.
DELIVERED_ON_RETRY = "Delivered to the ERP on a later attempt."


class ConflictService:
    def __init__(
        self,
        repo: ConflictRepository,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        rules: SeverityRuleRepository | None = None,
        classifier: CauseClassifier | None = None,
    ) -> None:
        self._repo = repo
        self._clock = clock
        self._rules = rules if rules is not None else InMemorySeverityRules()
        self._classifier = classifier if classifier is not None else UnavailableCauseClassifier()

    def severity_rules(self) -> list[SeverityRule]:
        return self._rules.list()

    def set_severity_rule(
        self, category: str, *, when_rejected: str, when_retrying: str
    ) -> SeverityRule:
        """Changes how urgent one cause is. Applies to conflicts opened from now on."""
        if self._rules.get(category) is None:
            raise ValueError(f"unknown cause '{category}'")
        rule = SeverityRule(
            category=category,
            when_rejected=_severity(when_rejected),
            when_retrying=_severity(when_retrying),
        )
        self._rules.update(rule)
        return rule

    def record_failure(
        self,
        *,
        tenant_id: str,
        order_id: str,
        reason_code: str,
        reason: str,
        terminal: bool,
    ) -> OrderConflict:
        """Opens a conflict for this order, or updates the open one. A rejected delivery is
        high severity; a transient one, still being retried, is medium."""
        rule = self._rules.get(classify(reason_code, reason).value)
        severity = (
            (rule.when_rejected if terminal else rule.when_retrying) if rule else Severity.HIGH
        )
        # Computed once, here, not on every later read (see ADR history / 0022's migration
        # note): a rule-recognised message never touches the classifier at all; only a
        # message the rule puts in OTHER asks it, and only once per failure, not once per
        # GraphQL read.
        category, category_source = cause_of(reason_code, reason, self._classifier)
        existing = self._repo.find_open_for_order(order_id)
        if existing is None:
            now = self._clock()
            conflict = OrderConflict(
                conflict_id=generate_id("cnf"),
                tenant_id=tenant_id,
                order_id=order_id,
                reason_code=reason_code,
                reason=reason,
                severity=severity,
                status=ConflictStatus.OPEN,
                attempts=1,
                assigned_to=None,
                resolution=None,
                resolution_note="",
                opened_at=now,
                sla_due_at=now + SLA,
                resolved_at=None,
                category=category.value,
                category_source=category_source,
            )
            try:
                self._repo.add(conflict)
                return conflict
            except OpenConflictExists:
                # A concurrent failure opened it first. Fall through and update that one.
                existing = self._repo.find_open_for_order(order_id)
                if existing is None:
                    raise
        existing.reason_code = reason_code
        existing.reason = reason
        existing.severity = severity
        existing.category = category.value
        existing.category_source = category_source
        existing.attempts += 1
        self._repo.update(existing)
        return existing

    def close_for_order(self, order_id: str) -> OrderConflict | None:
        """Closes the open conflict for an order whose delivery has now succeeded. Returns None
        when there was nothing open, which is the usual case."""
        existing = self._repo.find_open_for_order(order_id)
        if existing is None:
            return None
        existing.status = ConflictStatus.RESOLVED
        existing.resolution_note = DELIVERED_ON_RETRY
        existing.resolved_at = self._clock()
        self._repo.update(existing)
        return existing

    def list(self, status: ConflictStatus | None = None) -> list[OrderConflict]:
        return self._repo.list(status)

    def get(self, conflict_id: str) -> OrderConflict:
        conflict = self._repo.get(conflict_id)
        if conflict is None:
            raise ConflictNotFound(conflict_id)
        return conflict

    def is_open(self, conflict: OrderConflict) -> bool:
        return conflict.status in OPEN_STATUSES


def _severity(value: str) -> Severity:
    try:
        return Severity(value)
    except ValueError as e:
        raise ValueError(f"unknown severity '{value}'") from e
