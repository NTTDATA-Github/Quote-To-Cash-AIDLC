"""Provision the NetSuite connection and bind it to the same reseller as Odoo (idempotent).

Registers connection `conn_netsuite` (NetSuite, SuiteTalk REST) and binds it to tenant
`tnt_demo`, so one reseller is connected to both Odoo and NetSuite at once. The binding's
`erp_customer_id` is `101`; the subsidiary route's `erp_company_id` is `NS1`, which the
sales orders in the NetSuite instance carry, so the discovery/reconcile path adopts them
(same shape as the Odoo integration).

The secret stored in Secrets Manager is the NetSuite TBA JSON blob
`{"consumer_secret": ..., "token_secret": ...}` — the one-secret contract the adapter
expects (see docs/erps/netsuite/README.md).

Idempotent and self-migrating: it also removes any artifacts left by an earlier
`conn_netsuite_local` naming (connection, binding, route, and any orders adopted under it)
so a re-run converges on the professional identifiers.

Usage:
    DATABASE_URL=postgresql+psycopg2://portal:portal@localhost:5432/portal \\
    AWS_ENDPOINT_URL=http://localhost:4566 \\
        python -m scripts.seed_netsuite
"""

from __future__ import annotations

import json
import os

from sqlalchemy import create_engine, text
from src.shared.secrets.aws import SecretsManagerSecretStore

_CONNECTION_ID = "conn_netsuite"
_SECRET_REF = "netsuite/tba-credentials"
_WEBHOOK_SECRET_REF = "local:netsuite-webhook-secret"
_WEBHOOK_SECRET = "ns-webhook-demo"
_SECRET_VALUE = json.dumps(
    {
        "consumer_secret": "7c1f9a4b2e8d46a3b5c0e9f1a7d2b4c6",
        "token_secret": "a3b5c0e9f1a7d2b4c67c1f9a4b2e8d46",
    }
)
_CREDENTIALS = json.dumps(
    {
        "account_id": "TSTDRV1458972",
        "consumer_key": "a1b2c3d4e5f60718293a4b5c6d7e8f90",
        "token_id": "90f8e7d6c5b4a3920817f6e5d4c3b2a1",
    }
)

# Any residue from the earlier `conn_netsuite_local` naming — removed so the UI only ever
# shows the professional identifiers. Scoped strictly to the NetSuite connection.
_CLEANUP = [
    text("DELETE FROM order_status_history WHERE order_id LIKE 'ord_conn_netsuite_local%'"),
    text(
        "DELETE FROM orders WHERE owning_connection_id = 'conn_netsuite_local' "
        "OR order_id LIKE 'ord_conn_netsuite_local%'"
    ),
    text("DELETE FROM events WHERE stream_id LIKE 'ord_conn_netsuite_local%'"),
    text("DELETE FROM snapshots WHERE stream_id LIKE 'ord_conn_netsuite_local%'"),
    text("DELETE FROM outbox WHERE stream_id LIKE 'ord_conn_netsuite_local%'"),
    text("DELETE FROM subsidiary_routes WHERE connection_id = 'conn_netsuite_local'"),
    text("DELETE FROM tenant_connection_bindings WHERE connection_id = 'conn_netsuite_local'"),
    text("DELETE FROM erp_connections WHERE connection_id = 'conn_netsuite_local'"),
]

_STATEMENTS = [
    text(
        """
        INSERT INTO erp_connections
            (connection_id, erp_type, instance_label, base_url, credentials, secret_ref,
             webhook_secret_ref, status)
        VALUES
            (:connection_id, 'NETSUITE', 'NetSuite', 'http://127.0.0.1:8075',
             CAST(:credentials AS jsonb), :secret_ref, :webhook_secret_ref, 'ACTIVE')
        ON CONFLICT (connection_id) DO UPDATE SET
            instance_label = EXCLUDED.instance_label,
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
            ('bind_netsuite', 'tnt_demo', :connection_id, '101', 'VERIFIED')
        ON CONFLICT (binding_id) DO UPDATE SET
            connection_id = EXCLUDED.connection_id,
            erp_customer_id = EXCLUDED.erp_customer_id
        """
    ),
    text(
        """
        INSERT INTO subsidiaries (subsidiary_id, name, country, language)
        VALUES ('sub_netsuite', 'Northwind Trading Co.', 'US', 'en_US')
        ON CONFLICT (subsidiary_id) DO UPDATE SET name = EXCLUDED.name
        """
    ),
    text(
        """
        INSERT INTO subsidiary_routes (subsidiary_id, connection_id, erp_company_id)
        VALUES ('sub_netsuite', :connection_id, 'NS1')
        ON CONFLICT (subsidiary_id) DO UPDATE SET
            connection_id = EXCLUDED.connection_id,
            erp_company_id = EXCLUDED.erp_company_id
        """
    ),
]


def _put_secret() -> None:
    endpoint = os.environ.get("AWS_ENDPOINT_URL")
    if not endpoint:
        print("AWS_ENDPOINT_URL is unset — NetSuite secret was not stored")
        return
    store = SecretsManagerSecretStore(
        endpoint_url=endpoint, region_name=os.environ.get("AWS_DEFAULT_REGION", "us-east-1")
    )
    store.put_secret(_SECRET_REF, _SECRET_VALUE)
    store.put_secret(_WEBHOOK_SECRET_REF, _WEBHOOK_SECRET)


def main() -> None:
    url = os.environ.get(
        "DATABASE_URL", "postgresql+psycopg2://portal:portal@localhost:5432/portal"
    )
    engine = create_engine(url, future=True)
    params = {
        "connection_id": _CONNECTION_ID,
        "credentials": _CREDENTIALS,
        "secret_ref": _SECRET_REF,
        "webhook_secret_ref": _WEBHOOK_SECRET_REF,
    }
    with engine.begin() as connection:
        for statement in _CLEANUP:
            connection.execute(statement)
        for statement in _STATEMENTS:
            connection.execute(statement, params)
    _put_secret()
    print("NetSuite connection provisioned: conn_netsuite (NetSuite), bound to reseller tnt_demo,")
    print("subsidiary Northwind Trading Co. routed to it.")


if __name__ == "__main__":
    main()
