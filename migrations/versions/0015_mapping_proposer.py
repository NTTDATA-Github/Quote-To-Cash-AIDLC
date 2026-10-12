"""ERP field-mapping proposer: canonical schema registry + proposal job store.

Folds the former standalone `erp-mapping-service` into the portal. Both tables are
operator-only (the proposer reads ERP field names and sample values — ERP identity, never
a reseller surface), so no row-level security: the operator GraphQL schema is the only
reader/writer and it already requires the OPERATOR role.

`mapping_jobs` is a simple claimable work queue (status PENDING -> PROCESSING -> DONE /
FAILED); the `mapping` worker role claims rows with `FOR UPDATE SKIP LOCKED`.

Revision ID: 0015_mapping_proposer
Revises: 0014_one_odoo_one_subsidiary
Create Date: 2026-10-12
"""

from __future__ import annotations

from alembic import op

revision = "0015_mapping_proposer"
down_revision = "0014_one_odoo_one_subsidiary"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE canonical_schemas (
            name        TEXT PRIMARY KEY,
            csv_text    TEXT NOT NULL,
            created_at  TIMESTAMPTZ NOT NULL
        );

        CREATE TABLE mapping_jobs (
            job_id               TEXT PRIMARY KEY,
            erp_name             TEXT NOT NULL,
            status               TEXT NOT NULL,
            canonical_fields_csv TEXT NOT NULL,
            sample_exports       JSONB NOT NULL DEFAULT '{}'::jsonb,
            schema_name          TEXT,
            result               JSONB,
            error                TEXT,
            adapter_run_id       TEXT,
            created_at           TIMESTAMPTZ NOT NULL
        );

        -- the worker's claim query: pending jobs, oldest first
        CREATE INDEX mapping_jobs_pending_idx
            ON mapping_jobs (created_at)
            WHERE status = 'PENDING';
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP INDEX IF EXISTS mapping_jobs_pending_idx;
        DROP TABLE IF EXISTS mapping_jobs;
        DROP TABLE IF EXISTS canonical_schemas;
        """
    )
