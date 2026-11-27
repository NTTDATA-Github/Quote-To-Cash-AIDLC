"""Postgres conflict repository on `order_conflicts`."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import Column, DateTime, Integer, MetaData, String, Table, select, update
from sqlalchemy.exc import IntegrityError

from ..domain.models import (
    OPEN_STATUSES,
    ConflictStatus,
    OpenConflictExists,
    OrderConflict,
    Resolution,
    Severity,
    SeverityRule,
)

if TYPE_CHECKING:
    from sqlalchemy.engine import Row
    from sqlalchemy.orm import Session, sessionmaker

_metadata = MetaData()

order_conflicts_table = Table(
    "order_conflicts",
    _metadata,
    Column("conflict_id", String, primary_key=True),
    Column("tenant_id", String, nullable=False),
    Column("order_id", String, nullable=False),
    Column("reason_code", String, nullable=False),
    Column("reason", String, nullable=False),
    Column("severity", String, nullable=False),
    Column("status", String, nullable=False),
    Column("attempts", Integer, nullable=False),
    Column("assigned_to", String),
    Column("resolution", String),
    Column("resolution_note", String, nullable=False, server_default=""),
    Column("opened_at", DateTime(timezone=True), nullable=False),
    Column("sla_due_at", DateTime(timezone=True), nullable=False),
    Column("resolved_at", DateTime(timezone=True)),
    Column("category", String),
    Column("category_source", String),
)


def _to_model(row: Row) -> OrderConflict:
    return OrderConflict(
        conflict_id=row.conflict_id,
        tenant_id=row.tenant_id,
        order_id=row.order_id,
        reason_code=row.reason_code,
        reason=row.reason,
        severity=Severity(row.severity),
        status=ConflictStatus(row.status),
        attempts=row.attempts,
        assigned_to=row.assigned_to,
        resolution=Resolution(row.resolution) if row.resolution else None,
        resolution_note=row.resolution_note,
        opened_at=row.opened_at,
        sla_due_at=row.sla_due_at,
        resolved_at=row.resolved_at,
        category=row.category,
        category_source=row.category_source,
    )


def _values(c: OrderConflict) -> dict[str, object]:
    return {
        "conflict_id": c.conflict_id,
        "tenant_id": c.tenant_id,
        "order_id": c.order_id,
        "reason_code": c.reason_code,
        "reason": c.reason,
        "severity": c.severity.value,
        "status": c.status.value,
        "attempts": c.attempts,
        "assigned_to": c.assigned_to,
        "resolution": c.resolution.value if c.resolution else None,
        "resolution_note": c.resolution_note,
        "opened_at": c.opened_at,
        "sla_due_at": c.sla_due_at,
        "resolved_at": c.resolved_at,
        "category": c.category,
        "category_source": c.category_source,
    }


class PostgresConflictRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def add(self, conflict: OrderConflict) -> None:
        try:
            with self._session_factory.begin() as session:
                session.execute(order_conflicts_table.insert().values(**_values(conflict)))
        except IntegrityError as exc:
            # 23505 is the partial unique index: another open conflict already exists for the order.
            if getattr(exc.orig, "pgcode", None) == "23505":
                raise OpenConflictExists(conflict.order_id) from exc
            raise

    def get(self, conflict_id: str) -> OrderConflict | None:
        with self._session_factory() as session:
            row = session.execute(
                select(order_conflicts_table).where(
                    order_conflicts_table.c.conflict_id == conflict_id
                )
            ).first()
        return _to_model(row) if row else None

    def update(self, conflict: OrderConflict) -> None:
        with self._session_factory.begin() as session:
            session.execute(
                update(order_conflicts_table)
                .where(order_conflicts_table.c.conflict_id == conflict.conflict_id)
                .values(**_values(conflict))
            )

    def find_open_for_order(self, order_id: str) -> OrderConflict | None:
        open_values = [s.value for s in OPEN_STATUSES]
        with self._session_factory() as session:
            row = session.execute(
                select(order_conflicts_table)
                .where(order_conflicts_table.c.order_id == order_id)
                .where(order_conflicts_table.c.status.in_(open_values))
            ).first()
        return _to_model(row) if row else None

    def list(self, status: ConflictStatus | None) -> list[OrderConflict]:
        query = select(order_conflicts_table).order_by(order_conflicts_table.c.opened_at.desc())
        if status is not None:
            query = query.where(order_conflicts_table.c.status == status.value)
        with self._session_factory() as session:
            return [_to_model(r) for r in session.execute(query).all()]


severity_rules_table = Table(
    "conflict_severity_rules",
    _metadata,
    Column("category", String, primary_key=True),
    Column("when_rejected", String, nullable=False),
    Column("when_retrying", String, nullable=False),
)


class PostgresSeverityRuleRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def list(self) -> list[SeverityRule]:
        with self._session_factory() as session:
            rows = session.execute(select(severity_rules_table)).all()
        return [_rule_from_row(r) for r in rows]

    def get(self, category: str) -> SeverityRule | None:
        with self._session_factory() as session:
            row = session.execute(
                select(severity_rules_table).where(severity_rules_table.c.category == category)
            ).first()
        return _rule_from_row(row) if row is not None else None

    def update(self, rule: SeverityRule) -> None:
        with self._session_factory.begin() as session:
            session.execute(
                severity_rules_table.update()
                .where(severity_rules_table.c.category == rule.category)
                .values(
                    when_rejected=rule.when_rejected.value, when_retrying=rule.when_retrying.value
                )
            )


def _rule_from_row(row: Row) -> SeverityRule:
    return SeverityRule(
        category=row.category,
        when_rejected=Severity(row.when_rejected),
        when_retrying=Severity(row.when_retrying),
    )
