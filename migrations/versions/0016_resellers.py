"""Reseller display names.

Every other reference concept already splits a stable id from a human-facing name
(`erp_connections.instance_label`, `subsidiaries.name`) — tenants were the one gap, so
every "Reseller" column in the UI showed the raw `tenant_id` partition key. `tenant_id`
stays exactly as-is everywhere else (RLS, Cognito's `custom:tenant_id`, webhook URLs);
this table only adds the label.

Backfilled from every tenant_id already bound to a connection, name defaulting to the
tenant_id itself (the same fallback the UI used before this table existed) — an operator
renames it from there.

Revision ID: 0016_resellers
Revises: 0015_mapping_proposer
Create Date: 2026-10-14
"""

from __future__ import annotations

from alembic import op

revision = "0016_resellers"
down_revision = "0015_mapping_proposer"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE resellers (
            tenant_id TEXT PRIMARY KEY,
            name      TEXT NOT NULL
        );

        INSERT INTO resellers (tenant_id, name)
        SELECT DISTINCT tenant_id, tenant_id FROM tenant_connection_bindings
        ON CONFLICT (tenant_id) DO NOTHING;
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS resellers;")
