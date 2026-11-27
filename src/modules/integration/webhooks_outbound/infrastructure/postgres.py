"""Postgres-backed outbound-webhook repositories on `webhook_endpoints` +
`webhook_deliveries` (migration 0004)."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, Column, DateTime, Integer, MetaData, String, Table, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import insert as pg_insert

from src.shared.erp_auth import AuthType
from src.shared.types import TenantId, WebhookEndpointId

from ..domain.models import DeliveryStatus, WebhookDelivery, WebhookEndpoint

if TYPE_CHECKING:
    from sqlalchemy.engine import Row
    from sqlalchemy.orm import Session, sessionmaker

_metadata = MetaData()

webhook_endpoints_table = Table(
    "webhook_endpoints",
    _metadata,
    Column("endpoint_id", String, primary_key=True),
    Column("tenant_id", String, nullable=False),
    Column("name", String, nullable=False),
    Column("url", String, nullable=False),
    Column("secret_ref", String, nullable=False),
    Column("event_types", JSONB),
    Column("is_active", Boolean, nullable=False),
    # Credential we send to the receiver (migration 0018). The secret itself is in the
    # secret store under auth_secret_ref, never in this row.
    Column("auth_type", String, nullable=False, server_default="NONE"),
    Column("auth_params", JSONB, nullable=False, server_default="{}"),
    Column("auth_secret_ref", String),
)

webhook_deliveries_table = Table(
    "webhook_deliveries",
    _metadata,
    Column("delivery_id", String, primary_key=True),
    Column("endpoint_id", String, nullable=False),
    Column("tenant_id", String, nullable=False),
    Column("order_id", String, nullable=False),
    Column("event_type", String, nullable=False),
    Column("event_id", String, nullable=False),
    Column("occurred_at", DateTime(timezone=True), nullable=False),
    Column("status", String, nullable=False),
    Column("attempts", Integer, nullable=False),
    Column("last_response", String),
    Column("payload", JSONB, nullable=False),
)


def _endpoint_from_row(row: Row) -> WebhookEndpoint:
    return WebhookEndpoint(
        endpoint_id=WebhookEndpointId(row.endpoint_id),
        tenant_id=TenantId(row.tenant_id),
        name=row.name,
        url=row.url,
        secret_ref=row.secret_ref,
        event_types=frozenset(row.event_types) if row.event_types else None,
        is_active=row.is_active,
        auth_type=AuthType(row.auth_type),
        auth_params=dict(row.auth_params or {}),
        auth_secret_ref=row.auth_secret_ref,
    )


def _delivery_from_row(row: Row) -> WebhookDelivery:
    return WebhookDelivery(
        delivery_id=row.delivery_id,
        endpoint_id=WebhookEndpointId(row.endpoint_id),
        tenant_id=TenantId(row.tenant_id),
        order_id=row.order_id,
        event_type=row.event_type,
        event_id=row.event_id,
        occurred_at=row.occurred_at,
        status=DeliveryStatus(row.status),
        attempts=row.attempts,
        last_response=row.last_response,
        payload=row.payload,
    )


class PostgresWebhookEndpointRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def add(self, endpoint: WebhookEndpoint) -> None:
        session = self._session_factory()
        try:
            session.execute(
                webhook_endpoints_table.insert().values(
                    endpoint_id=str(endpoint.endpoint_id),
                    tenant_id=str(endpoint.tenant_id),
                    name=endpoint.name,
                    url=endpoint.url,
                    secret_ref=endpoint.secret_ref,
                    event_types=list(endpoint.event_types)
                    if endpoint.event_types is not None
                    else None,
                    is_active=endpoint.is_active,
                    auth_type=endpoint.auth_type.value,
                    auth_params=dict(endpoint.auth_params),
                    auth_secret_ref=endpoint.auth_secret_ref,
                )
            )
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def get(self, endpoint_id: WebhookEndpointId) -> WebhookEndpoint | None:
        session = self._session_factory()
        try:
            row = session.execute(
                select(webhook_endpoints_table).where(
                    webhook_endpoints_table.c.endpoint_id == str(endpoint_id)
                )
            ).first()
        finally:
            session.close()
        return _endpoint_from_row(row) if row is not None else None

    def update(self, endpoint: WebhookEndpoint) -> None:
        session = self._session_factory()
        try:
            session.execute(
                webhook_endpoints_table.update()
                .where(webhook_endpoints_table.c.endpoint_id == str(endpoint.endpoint_id))
                .values(is_active=endpoint.is_active)
            )
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def list_by_tenant(self, tenant_id: TenantId) -> list[WebhookEndpoint]:
        session = self._session_factory()
        try:
            rows = session.execute(
                select(webhook_endpoints_table).where(
                    webhook_endpoints_table.c.tenant_id == str(tenant_id)
                )
            ).all()
        finally:
            session.close()
        return [_endpoint_from_row(row) for row in rows]


class PostgresWebhookDeliveryRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def find(self, endpoint_id: WebhookEndpointId, event_id: str) -> WebhookDelivery | None:
        session = self._session_factory()
        try:
            row = session.execute(
                select(webhook_deliveries_table).where(
                    webhook_deliveries_table.c.endpoint_id == str(endpoint_id),
                    webhook_deliveries_table.c.event_id == event_id,
                )
            ).first()
        finally:
            session.close()
        return _delivery_from_row(row) if row is not None else None

    def upsert(self, delivery: WebhookDelivery) -> None:
        values = {
            "delivery_id": delivery.delivery_id,
            "endpoint_id": str(delivery.endpoint_id),
            "tenant_id": str(delivery.tenant_id),
            "order_id": delivery.order_id,
            "event_type": delivery.event_type,
            "event_id": delivery.event_id,
            "occurred_at": delivery.occurred_at,
            "status": delivery.status.value,
            "attempts": delivery.attempts,
            "last_response": delivery.last_response,
            "payload": json.loads(json.dumps(delivery.payload)),  # ensure plain-JSON-serializable
        }
        session = self._session_factory()
        try:
            stmt = pg_insert(webhook_deliveries_table).values(**values)
            stmt = stmt.on_conflict_do_update(
                index_elements=["endpoint_id", "event_id"], set_=values
            )
            session.execute(stmt)
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def list_by_tenant(self, tenant_id: TenantId) -> list[WebhookDelivery]:
        session = self._session_factory()
        try:
            rows = session.execute(
                select(webhook_deliveries_table).where(
                    webhook_deliveries_table.c.tenant_id == str(tenant_id)
                )
            ).all()
        finally:
            session.close()
        return [_delivery_from_row(row) for row in rows]

    def list_all(self) -> list[WebhookDelivery]:
        session = self._session_factory()
        try:
            rows = session.execute(select(webhook_deliveries_table)).all()
        finally:
            session.close()
        return [_delivery_from_row(row) for row in rows]
