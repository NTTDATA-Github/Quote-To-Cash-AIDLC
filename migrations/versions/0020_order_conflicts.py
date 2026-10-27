"""Order conflicts: the operator queue for rejected and failing deliveries.

One open row per order: the service updates it on each new failure. Resolved and dismissed
rows stay for the audit trail.

Revision ID: 0020_order_conflicts
Revises: 0019_active_binding_uniqueness
Create Date: 2026-10-21
"""

from __future__ import annotations

from alembic import op

revision = "0020_order_conflicts"
down_revision = "0019_active_binding_uniqueness"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE order_conflicts (
            conflict_id     TEXT PRIMARY KEY,
            tenant_id       TEXT NOT NULL,
            order_id        TEXT NOT NULL,
            reason_code     TEXT NOT NULL,
            reason          TEXT NOT NULL,
            severity        TEXT NOT NULL,
            status          TEXT NOT NULL,
            attempts        INTEGER NOT NULL,
            assigned_to     TEXT,
            resolution      TEXT,
            resolution_note TEXT NOT NULL DEFAULT '',
            opened_at       TIMESTAMPTZ NOT NULL,
            sla_due_at      TIMESTAMPTZ NOT NULL,
            resolved_at     TIMESTAMPTZ
        );
        CREATE INDEX order_conflicts_order_idx ON order_conflicts (order_id);
        CREATE INDEX order_conflicts_status_idx ON order_conflicts (status);
        -- One open conflict per order. Closed conflicts (RESOLVED, DISMISSED) are history and
        -- do not count, so an order can have a new conflict after an earlier one closed.
        CREATE UNIQUE INDEX order_conflicts_one_open_per_order
            ON order_conflicts (order_id)
            WHERE status IN ('OPEN', 'IN_REVIEW');
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS order_conflicts;")
