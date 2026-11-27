"""A removed reseller link is history, so re-linking creates a new row.

Migration 0001 made (tenant_id, connection_id) and (connection_id, erp_customer_id) unique for
every row, including REMOVED ones. That blocked re-linking after a removal, and the workaround
was to overwrite the old row, which rewrote history. Both rules now apply to active links only:
a partial unique index WHERE status <> 'REMOVED'. Removed rows stay as they were.

Downgrade restores the old unique constraints. It fails if a reseller has both a removed link
and a new one for the same pair, so resolve those duplicates first.

Revision ID: 0019_active_binding_uniqueness
Revises: 0018_webhook_endpoint_auth
Create Date: 2026-10-26
"""

from __future__ import annotations

from alembic import op

revision = "0019_active_binding_uniqueness"
down_revision = "0018_webhook_endpoint_auth"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Drop every unique constraint on the table. 0001 left them unnamed, so look them up.
    op.execute(
        """
        DO $$
        DECLARE c record;
        BEGIN
            FOR c IN
                SELECT conname FROM pg_constraint
                WHERE conrelid = 'tenant_connection_bindings'::regclass AND contype = 'u'
            LOOP
                EXECUTE format(
                    'ALTER TABLE tenant_connection_bindings DROP CONSTRAINT %I', c.conname
                );
            END LOOP;
        END $$;
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX tenant_connection_bindings_active_pair
            ON tenant_connection_bindings (tenant_id, connection_id)
            WHERE status <> 'REMOVED';
        CREATE UNIQUE INDEX tenant_connection_bindings_active_customer
            ON tenant_connection_bindings (connection_id, erp_customer_id)
            WHERE status <> 'REMOVED';
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS tenant_connection_bindings_active_pair;")
    op.execute("DROP INDEX IF EXISTS tenant_connection_bindings_active_customer;")
    op.execute(
        """
        ALTER TABLE tenant_connection_bindings
            ADD CONSTRAINT tenant_connection_bindings_tenant_id_connection_id_key
                UNIQUE (tenant_id, connection_id),
            ADD CONSTRAINT tenant_connection_bindings_connection_id_erp_customer_id_key
                UNIQUE (connection_id, erp_customer_id);
        """
    )
