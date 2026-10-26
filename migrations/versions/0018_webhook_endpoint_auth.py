"""Outbound webhook endpoints can authenticate to the receiver.

An endpoint keeps its HMAC signing secret (proves the request came from us) and, now, an
optional credential we send to the receiver. `auth_type` says how it is sent (NONE,
API_KEY_HEADER, BEARER_TOKEN or BASIC); `auth_params` holds its non-secret settings such as
the header name or username; the credential itself lives in the secret store under
`auth_secret_ref`. Existing endpoints migrate to NONE, so they keep working unchanged.

Revision ID: 0018_webhook_endpoint_auth
Revises: 0017_connections_before_adapters
Create Date: 2026-10-26
"""

from __future__ import annotations

from alembic import op

revision = "0018_webhook_endpoint_auth"
down_revision = "0017_connections_before_adapters"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE webhook_endpoints
            ADD COLUMN auth_type TEXT NOT NULL DEFAULT 'NONE',
            ADD COLUMN auth_params JSONB NOT NULL DEFAULT '{}'::jsonb,
            ADD COLUMN auth_secret_ref TEXT
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE webhook_endpoints
            DROP COLUMN IF EXISTS auth_secret_ref,
            DROP COLUMN IF EXISTS auth_params,
            DROP COLUMN IF EXISTS auth_type
        """
    )
