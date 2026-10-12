"""Seed demo data for local development (idempotent).

One Odoo connection and a verified binding. Sales orders are read from Odoo for that
partner; this app does not create them.

The binding's erp_customer_id is Odoo's res.partner id (an integer). Partner 10 is
Acme Retail, the reseller's customer record in this demo database. The subsidiary's
erp_company_id is Odoo's res.company id. Company 1 is Northstar Distribution. A product
line is followed only when its Internal Reference is set. A quotation whose company id
is not recorded on a subsidiary is not adopted.

Usage:
    DATABASE_URL=postgresql+psycopg2://portal:portal@localhost:5432/portal \\
    AWS_ENDPOINT_URL=http://localhost:4566 \\
        python -m scripts.seed_demo
"""

from __future__ import annotations

import os

from sqlalchemy import create_engine, text
from src.shared.secrets.aws import SecretsManagerSecretStore

_LOGIN_SECRET = "local:odoo-admin-secret"
_WEBHOOK_SECRET = "local:odoo-webhook-demo-secret"

_STATEMENTS = [
    text(
        """
        INSERT INTO erp_connections
            (connection_id, erp_type, instance_label, base_url, credentials, secret_ref,
             webhook_secret_ref, status)
        VALUES
            ('conn_odoo_local', 'ODOO', 'Local Odoo (dev)', 'http://localhost:8069',
             '{"database":"odoo","username":"admin"}'::jsonb,
             :login_secret, :webhook_secret, 'ACTIVE')
        ON CONFLICT (connection_id) DO UPDATE SET
            base_url = EXCLUDED.base_url,
            credentials = EXCLUDED.credentials,
            secret_ref = EXCLUDED.secret_ref,
            webhook_secret_ref = EXCLUDED.webhook_secret_ref
        """
    ),
    text(
        """
        INSERT INTO tenant_connection_bindings
            (binding_id, tenant_id, connection_id, erp_customer_id, status)
        VALUES
            ('bind_demo', 'tnt_demo', 'conn_odoo_local', '10', 'VERIFIED')
        ON CONFLICT (binding_id) DO UPDATE SET erp_customer_id = EXCLUDED.erp_customer_id
        """
    ),
    text(
        """
        INSERT INTO subsidiaries (subsidiary_id, name, country, language)
        VALUES ('sub_demo', 'Northstar Distribution', 'US', 'en_US')
        ON CONFLICT (subsidiary_id) DO UPDATE SET name = EXCLUDED.name
        """
    ),
    text(
        """
        INSERT INTO subsidiary_routes (subsidiary_id, connection_id, erp_company_id)
        VALUES ('sub_demo', 'conn_odoo_local', '1')
        ON CONFLICT (subsidiary_id) DO UPDATE SET
            connection_id = EXCLUDED.connection_id,
            erp_company_id = EXCLUDED.erp_company_id
        """
    ),
]


def _put_secrets() -> None:
    endpoint = os.environ.get("AWS_ENDPOINT_URL")
    if not endpoint:
        print("AWS_ENDPOINT_URL is unset — Odoo login secret was not stored")
        return
    store = SecretsManagerSecretStore(
        endpoint_url=endpoint, region_name=os.environ.get("AWS_DEFAULT_REGION", "us-east-1")
    )
    store.put_secret(_LOGIN_SECRET, "admin")
    store.put_secret(_WEBHOOK_SECRET, "odoo-webhook-demo")


def main() -> None:
    url = os.environ.get(
        "DATABASE_URL", "postgresql+psycopg2://portal:portal@localhost:5432/portal"
    )
    engine = create_engine(url, future=True)
    params = {"login_secret": _LOGIN_SECRET, "webhook_secret": _WEBHOOK_SECRET}
    with engine.begin() as connection:
        connection.execute(_STATEMENTS[0], params)
        for statement in _STATEMENTS[1:]:
            connection.execute(statement)
    _put_secrets()
    print("demo data seeded (connection, binding, subsidiary)")


if __name__ == "__main__":
    main()
