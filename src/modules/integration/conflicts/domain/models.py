"""Order conflict: one row per order that needs an operator decision."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import datetime


class ConflictStatus(str, Enum):
    OPEN = "OPEN"
    IN_REVIEW = "IN_REVIEW"
    RESOLVED = "RESOLVED"
    DISMISSED = "DISMISSED"


class Severity(str, Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


@dataclass(frozen=True)
class SeverityRule:
    """How urgent one cause is, depending on whether the ERP refused the order (rejected) or the
    delivery is still being retried. Operators edit these; they are data, not code."""

    category: str  # a ConflictCategory value
    when_rejected: Severity
    when_retrying: Severity


# The starting rules. Operators change them in the app; these are only the first values.
DEFAULT_SEVERITY_RULES: tuple[SeverityRule, ...] = (
    SeverityRule("CUSTOMER_ON_HOLD", Severity.HIGH, Severity.MEDIUM),
    SeverityRule("PRODUCT_NOT_FOUND", Severity.MEDIUM, Severity.MEDIUM),
    SeverityRule("PRICE_MISMATCH", Severity.MEDIUM, Severity.MEDIUM),
    SeverityRule("ADDRESS_PROBLEM", Severity.MEDIUM, Severity.MEDIUM),
    SeverityRule("DUPLICATE_ORDER", Severity.LOW, Severity.LOW),
    SeverityRule("ERP_UNREACHABLE", Severity.MEDIUM, Severity.MEDIUM),
    # Unknown messages are treated as serious until someone has looked at them.
    SeverityRule("OTHER", Severity.HIGH, Severity.MEDIUM),
)


class Resolution(str, Enum):
    ACCEPT_ERP = "ACCEPT_ERP"
    ACCEPT_RESELLER = "ACCEPT_RESELLER"
    DISMISS = "DISMISS"


OPEN_STATUSES = frozenset({ConflictStatus.OPEN, ConflictStatus.IN_REVIEW})


class ConflictNotFound(Exception):
    pass


class ConflictClosed(Exception):
    """The conflict is already resolved or dismissed; it can't change again."""


class ConflictExplanationUnavailable(Exception):
    """No AI summary can be given right now: no provider is set up, or the provider failed."""


class OpenConflictExists(Exception):
    """An order can have one open conflict at a time. The database enforces this too (a partial
    unique index), so a race between two failed deliveries cannot create a second row."""


@dataclass
class OrderConflict:
    conflict_id: str
    tenant_id: str
    order_id: str
    reason_code: str
    reason: str
    severity: Severity
    status: ConflictStatus
    attempts: int
    assigned_to: str | None
    resolution: Resolution | None
    resolution_note: str
    opened_at: datetime
    sla_due_at: datetime
    resolved_at: datetime | None
    # Computed once in ConflictService.record_failure, not on every read. None only for
    # rows recorded before this field existed — the read path falls back to the rule-only
    # classifier for those, never a live LLM call for old history.
    category: str | None = None
    category_source: str | None = None
