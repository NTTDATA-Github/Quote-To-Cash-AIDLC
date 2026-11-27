"""Ports the conflicts service depends on (implemented in infrastructure/)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from ..domain.categories import ConflictCategory
    from ..domain.models import ConflictStatus, OrderConflict, SeverityRule


class ConflictRepository(Protocol):
    def add(self, conflict: OrderConflict) -> None: ...
    def get(self, conflict_id: str) -> OrderConflict | None: ...
    def update(self, conflict: OrderConflict) -> None: ...
    def find_open_for_order(self, order_id: str) -> OrderConflict | None: ...
    def list(self, status: ConflictStatus | None) -> list[OrderConflict]: ...


class SeverityRuleRepository(Protocol):
    def list(self) -> list[SeverityRule]: ...
    def get(self, category: str) -> SeverityRule | None: ...
    def update(self, rule: SeverityRule) -> None: ...


class CauseClassifier(Protocol):
    """Suggests a cause for an ERP message no rule recognised. None when it can't say."""

    def classify(self, message: str) -> ConflictCategory | None: ...


class ConflictExplainer(Protocol):
    """Writes a short plain-English explanation of one conflict for the operator. The model sees
    facts only; it proposes nothing and changes nothing."""

    def explain(self, conflict: OrderConflict, reseller_name: str) -> str: ...
