"""ADR-0021/0022: a connection can exist before its adapter does; mapping jobs are
deduped per ERP type via the connection they were probed from.

- `erp_connections.auth_type` — how the generic onboarding probe (not the real adapter,
  which has its own hardcoded auth logic) authenticates to a not-yet-adapted connection.
  `credentials` (JSONB, migration 0006) already carries the non-secret auth params
  (header name, username) — no new bag needed, just the one new field naming which
  strategy to apply.
- `mapping_jobs.connection_id` — nullable: a job probed live from a connection carries
  it; a job built from manually-uploaded sample files (still fully supported, ADR-0021)
  has none. FK, not enforced NOT NULL, so the existing manual-upload path needs no
  backfill.

`erp_connections.erp_type` itself needs no migration — already plain `TEXT` since
migration 0001, never a DB-level enum.

Revision ID: 0017_connections_before_adapters
Revises: 0016_resellers
Create Date: 2026-10-15
"""

from __future__ import annotations

from alembic import op

revision = "0017_connections_before_adapters"
down_revision = "0016_resellers"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE erp_connections ADD COLUMN auth_type TEXT NOT NULL DEFAULT 'NONE';
        ALTER TABLE mapping_jobs ADD COLUMN connection_id TEXT
            REFERENCES erp_connections (connection_id);
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE mapping_jobs DROP COLUMN IF EXISTS connection_id;
        ALTER TABLE erp_connections DROP COLUMN IF EXISTS auth_type;
        """
    )
