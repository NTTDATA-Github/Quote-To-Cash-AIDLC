"""Target architecture initial schema: event store + outbox + projections + config/tenancy.

Single PostgreSQL database. Includes the three uniqueness invariants that guarantee
tenant isolation, and row-level security on reseller-readable projections.

Revision ID: 0001_target_architecture
Revises:
Create Date: 2026-09-22
"""

from __future__ import annotations

from alembic import op

revision = "0001_target_architecture"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        -- ============ event store (source of truth for the Order aggregate) ============
        CREATE TABLE events (
            id             BIGSERIAL PRIMARY KEY,
            stream_id      TEXT NOT NULL,
            aggregate_type TEXT NOT NULL,
            version        INTEGER NOT NULL,
            event_type     TEXT NOT NULL,
            event_id       TEXT NOT NULL UNIQUE,
            occurred_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
            tenant_id      TEXT,
            correlation_id TEXT,
            payload        JSONB NOT NULL DEFAULT '{}'::jsonb,
            UNIQUE (stream_id, version)          -- optimistic concurrency
        );
        CREATE INDEX idx_events_stream ON events (stream_id, version);

        CREATE TABLE snapshots (
            stream_id TEXT PRIMARY KEY,
            version   INTEGER NOT NULL,
            state     JSONB NOT NULL,
            taken_at  TIMESTAMPTZ NOT NULL DEFAULT now()
        );

        -- ============ transactional outbox (relayed to the message bus) ============
        CREATE TABLE outbox (
            id             BIGSERIAL PRIMARY KEY,
            event_id       TEXT NOT NULL,
            event_type     TEXT NOT NULL,
            stream_id      TEXT NOT NULL,
            aggregate_type TEXT NOT NULL,
            tenant_id      TEXT,
            correlation_id TEXT,
            payload        JSONB NOT NULL DEFAULT '{}'::jsonb,
            occurred_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
            published_at   TIMESTAMPTZ
        );
        CREATE INDEX idx_outbox_unpublished ON outbox (id) WHERE published_at IS NULL;

        -- ============ consumer idempotency ============
        CREATE TABLE processed_events (
            consumer  TEXT NOT NULL,
            event_id  TEXT NOT NULL,
            handled_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (consumer, event_id)
        );

        -- ============ config / tenancy (CRUD) ============
        CREATE TABLE erp_connections (
            connection_id  TEXT PRIMARY KEY,
            erp_type       TEXT NOT NULL,
            instance_label TEXT NOT NULL,
            base_url       TEXT NOT NULL,
            database       TEXT NOT NULL,
            username       TEXT NOT NULL,
            secret_ref     TEXT NOT NULL,          -- secret store reference, never a raw credential
            status         TEXT NOT NULL DEFAULT 'ACTIVE'
        );

        CREATE TABLE tenant_connection_bindings (
            binding_id      TEXT PRIMARY KEY,
            tenant_id       TEXT NOT NULL,
            connection_id   TEXT NOT NULL REFERENCES erp_connections (connection_id),
            erp_customer_id TEXT NOT NULL,
            status          TEXT NOT NULL DEFAULT 'TO_VERIFY',
            UNIQUE (tenant_id, connection_id),          -- a reseller: one binding per connection
            UNIQUE (connection_id, erp_customer_id)     -- an ERP customer maps to one tenant
        );

        CREATE TABLE items (
            item_id              TEXT PRIMARY KEY,
            sku                  TEXT NOT NULL UNIQUE,
            name                 TEXT NOT NULL,
            owning_connection_id TEXT NOT NULL REFERENCES erp_connections (connection_id)
        );

        -- ============ projections (CQRS read models) + reverse-routing key ============
        CREATE TABLE orders (
            order_id             TEXT PRIMARY KEY,
            tenant_id            TEXT NOT NULL,
            client_reference     TEXT NOT NULL,
            state                TEXT NOT NULL,
            owning_connection_id TEXT,
            erp_order_id         TEXT,
            created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (owning_connection_id, erp_order_id)   -- reverse routing: one owning order
        );
        CREATE INDEX idx_orders_tenant ON orders (tenant_id);

        CREATE TABLE order_status_history (
            id          BIGSERIAL PRIMARY KEY,
            order_id    TEXT NOT NULL REFERENCES orders (order_id),
            tenant_id   TEXT NOT NULL,
            state       TEXT NOT NULL,
            reason      TEXT,
            occurred_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        CREATE INDEX idx_status_order ON order_status_history (order_id);

        CREATE TABLE webhook_endpoints (
            endpoint_id  TEXT PRIMARY KEY,
            tenant_id    TEXT NOT NULL,
            url          TEXT NOT NULL,
            secret_hash  TEXT NOT NULL,
            active       BOOLEAN NOT NULL DEFAULT TRUE,
            created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
        );

        CREATE TABLE audit_log (
            id          BIGSERIAL PRIMARY KEY,
            actor       TEXT NOT NULL,
            action      TEXT NOT NULL,
            entity      TEXT NOT NULL,
            before      JSONB,
            after       JSONB,
            occurred_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );

        -- ============ row-level security (defense in depth for reseller reads) ============
        -- App sets `SET app.tenant_id = '<tenant>'` per request/connection.
        ALTER TABLE orders ENABLE ROW LEVEL SECURITY;
        CREATE POLICY orders_tenant_isolation ON orders
            USING (tenant_id = current_setting('app.tenant_id', true));

        ALTER TABLE order_status_history ENABLE ROW LEVEL SECURITY;
        CREATE POLICY status_tenant_isolation ON order_status_history
            USING (tenant_id = current_setting('app.tenant_id', true));
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TABLE IF EXISTS audit_log, webhook_endpoints, order_status_history, orders,
            items, tenant_connection_bindings, erp_connections, processed_events,
            outbox, snapshots, events CASCADE;
        """
    )
