"""Postgres-backed connection repository — the `ConnectionRepository` port on `erp_connections`."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import Column, MetaData, String, Table, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import insert as pg_insert

from src.shared.types import ConnectionId

from ..domain.models import ConnectionStatus, ErpConnection

if TYPE_CHECKING:
    from sqlalchemy.engine import Row
    from sqlalchemy.orm import Session, sessionmaker

_metadata = MetaData()

erp_connections_table = Table(
    "erp_connections",
    _metadata,
    Column("connection_id", String, primary_key=True),
    Column("erp_type", String, nullable=False),
    Column("instance_label", String, nullable=False),
    Column("base_url", String, nullable=False),
    Column("credentials", JSONB, nullable=False, server_default="{}"),
    Column("secret_ref", String, nullable=False),
    Column("status", String, nullable=False),
    Column("webhook_secret_ref", String),
    Column("auth_type", String, nullable=False, server_default="NONE"),
)


def _to_model(row: Row) -> ErpConnection:
    return ErpConnection(
        connection_id=ConnectionId(row.connection_id),
        erp_type=row.erp_type,
        instance_label=row.instance_label,
        base_url=row.base_url,
        credentials=dict(row.credentials or {}),
        secret_ref=row.secret_ref,
        status=ConnectionStatus(row.status),
        webhook_secret_ref=row.webhook_secret_ref,
        auth_type=row.auth_type,
    )


class PostgresConnectionRepository:
    """`ConnectionRepository` on `erp_connections`. `add` upserts by `connection_id`."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def add(self, connection: ErpConnection) -> None:
        values = {
            "connection_id": str(connection.connection_id),
            "erp_type": connection.erp_type,
            "instance_label": connection.instance_label,
            "base_url": connection.base_url,
            "credentials": dict(connection.credentials),
            "secret_ref": connection.secret_ref,
            "status": connection.status.value,
            "webhook_secret_ref": connection.webhook_secret_ref,
            "auth_type": connection.auth_type,
        }
        session = self._session_factory()
        try:
            stmt = pg_insert(erp_connections_table).values(**values)
            stmt = stmt.on_conflict_do_update(index_elements=["connection_id"], set_=values)
            session.execute(stmt)
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def get(self, connection_id: ConnectionId) -> ErpConnection | None:
        session = self._session_factory()
        try:
            row = session.execute(
                select(erp_connections_table).where(
                    erp_connections_table.c.connection_id == str(connection_id)
                )
            ).first()
        finally:
            session.close()
        return _to_model(row) if row is not None else None

    def update(self, connection: ErpConnection) -> None:
        session = self._session_factory()
        try:
            session.execute(
                erp_connections_table.update()
                .where(erp_connections_table.c.connection_id == str(connection.connection_id))
                .values(status=connection.status.value, instance_label=connection.instance_label)
            )
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def list_active(self) -> list[ErpConnection]:
        session = self._session_factory()
        try:
            rows = session.execute(
                select(erp_connections_table).where(
                    erp_connections_table.c.status == ConnectionStatus.ACTIVE.value
                )
            ).all()
        finally:
            session.close()
        return [_to_model(row) for row in rows]

    def list_all(self) -> list[ErpConnection]:
        session = self._session_factory()
        try:
            rows = session.execute(select(erp_connections_table)).all()
        finally:
            session.close()
        return [_to_model(row) for row in rows]
