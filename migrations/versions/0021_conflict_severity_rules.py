"""Severity rules for order conflicts, editable by operators.

One row per cause: how urgent it is when the ERP rejects the order, and when the delivery is still
being retried. The conflict service reads these when it opens a conflict. Changing a rule applies to
conflicts opened after the change; existing conflicts keep the severity they were opened with.

Revision ID: 0021_conflict_severity_rules
Revises: 0020_order_conflicts
Create Date: 2026-10-27
"""

from __future__ import annotations

from alembic import op

revision = "0021_conflict_severity_rules"
down_revision = "0020_order_conflicts"
branch_labels = None
depends_on = None

_DEFAULTS = (
    ("CUSTOMER_ON_HOLD", "HIGH", "MEDIUM"),
    ("PRODUCT_NOT_FOUND", "MEDIUM", "MEDIUM"),
    ("PRICE_MISMATCH", "MEDIUM", "MEDIUM"),
    ("ADDRESS_PROBLEM", "MEDIUM", "MEDIUM"),
    ("DUPLICATE_ORDER", "LOW", "LOW"),
    ("ERP_UNREACHABLE", "MEDIUM", "MEDIUM"),
    ("OTHER", "HIGH", "MEDIUM"),
)


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE conflict_severity_rules (
            category       TEXT PRIMARY KEY,
            when_rejected  TEXT NOT NULL CHECK (when_rejected IN ('HIGH', 'MEDIUM', 'LOW')),
            when_retrying  TEXT NOT NULL CHECK (when_retrying IN ('HIGH', 'MEDIUM', 'LOW'))
        );
        """
    )
    values = ", ".join(f"('{c}', '{r}', '{t}')" for c, r, t in _DEFAULTS)
    op.execute(
        "INSERT INTO conflict_severity_rules (category, when_rejected, when_retrying) "
        f"VALUES {values};"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS conflict_severity_rules;")
