"""In-memory conflict repository (memory profile and tests)."""

from __future__ import annotations

import copy

from ..domain.models import (
    DEFAULT_SEVERITY_RULES,
    OPEN_STATUSES,
    ConflictStatus,
    OpenConflictExists,
    OrderConflict,
    SeverityRule,
)


class InMemorySeverityRules:
    def __init__(self) -> None:
        self._rules = {rule.category: rule for rule in DEFAULT_SEVERITY_RULES}

    def list(self) -> list[SeverityRule]:
        return list(self._rules.values())

    def get(self, category: str) -> SeverityRule | None:
        return self._rules.get(category)

    def update(self, rule: SeverityRule) -> None:
        self._rules[rule.category] = rule


class InMemoryConflictRepository:
    def __init__(self) -> None:
        self._rows: dict[str, OrderConflict] = {}

    def add(self, conflict: OrderConflict) -> None:
        if any(
            r.order_id == conflict.order_id and r.status in OPEN_STATUSES
            for r in self._rows.values()
        ):
            raise OpenConflictExists(conflict.order_id)
        self._rows[conflict.conflict_id] = copy.copy(conflict)

    def get(self, conflict_id: str) -> OrderConflict | None:
        row = self._rows.get(conflict_id)
        return copy.copy(row) if row else None

    def update(self, conflict: OrderConflict) -> None:
        self._rows[conflict.conflict_id] = copy.copy(conflict)

    def find_open_for_order(self, order_id: str) -> OrderConflict | None:
        for row in self._rows.values():
            if row.order_id == order_id and row.status in OPEN_STATUSES:
                return copy.copy(row)
        return None

    def list(self, status: ConflictStatus | None) -> list[OrderConflict]:
        rows = [copy.copy(r) for r in self._rows.values()]
        if status is not None:
            rows = [r for r in rows if r.status is status]
        return sorted(rows, key=lambda r: r.opened_at, reverse=True)
