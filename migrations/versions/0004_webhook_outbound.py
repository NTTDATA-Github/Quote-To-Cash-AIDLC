"""Outbound webhook dispatch: rebuild `webhook_endpoints` (from 0001's unused shape,
`secret_hash` couldn't have supported HMAC signing at send time — signing needs the raw
secret, not a hash of it) and add `webhook_deliveries`.

Revision ID: 0004_webhook_outbound
Revises: 0003_webhook_secret_ref
Create Date: 2026-09-27
"""

from __future__ import annotations

from alembic import op

revision = "0004_webhook_outbound"
down_revision = "0003_webhook_secret_ref"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        DROP TABLE IF EXISTS webhook_endpoints;

        CREATE TABLE webhook_endpoints (
            endpoint_id  TEXT PRIMARY KEY,
            tenant_id    TEXT NOT NULL,
            name         TEXT NOT NULL,
            url          TEXT NOT NULL,
            secret_ref   TEXT NOT NULL,      -- secret store ref, app-generated at registration
            event_types  JSONB,              -- null = subscribe to every dispatchable event
            is_active    BOOLEAN NOT NULL DEFAULT TRUE,
            created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        CREATE INDEX idx_webhook_endpoints_tenant ON webhook_endpoints (tenant_id);

        CREATE TABLE webhook_deliveries (
            delivery_id   TEXT PRIMARY KEY,
            endpoint_id   TEXT NOT NULL REFERENCES webhook_endpoints (endpoint_id),
            tenant_id     TEXT NOT NULL,
            order_id      TEXT NOT NULL,
            event_type    TEXT NOT NULL,
            event_id      TEXT NOT NULL,
            occurred_at   TIMESTAMPTZ NOT NULL,
            status        TEXT NOT NULL DEFAULT 'RETRYING',
            attempts      INTEGER NOT NULL DEFAULT 0,
            last_response TEXT,
            payload       JSONB NOT NULL DEFAULT '{}'::jsonb,
            updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (endpoint_id, event_id)
        );
        CREATE INDEX idx_webhook_deliveries_tenant ON webhook_deliveries (tenant_id);

        ALTER TABLE webhook_endpoints ENABLE ROW LEVEL SECURITY;
        CREATE POLICY webhook_endpoints_tenant_isolation ON webhook_endpoints
            USING (tenant_id = current_setting('app.tenant_id', true));

        ALTER TABLE webhook_deliveries ENABLE ROW LEVEL SECURITY;
        CREATE POLICY webhook_deliveries_tenant_isolation ON webhook_deliveries
            USING (tenant_id = current_setting('app.tenant_id', true));
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TABLE IF EXISTS webhook_deliveries;
        DROP TABLE IF EXISTS webhook_endpoints;

        CREATE TABLE webhook_endpoints (
            endpoint_id  TEXT PRIMARY KEY,
            tenant_id    TEXT NOT NULL,
            url          TEXT NOT NULL,
            secret_hash  TEXT NOT NULL,
            active       BOOLEAN NOT NULL DEFAULT TRUE,
            created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        """
    )
