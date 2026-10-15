"""Postgres-backed binding repository — the `BindingRepository` port on
`tenant_connection_bindings`.

The two `UNIQUE` constraints from migration 0001 are the real source of truth for the
uniqueness invariants; `BindingService` pre-checks in the app layer, but concurrent
requests race that check, so `add` turns the DB's `IntegrityError` into the same
`BindingConflict` the app layer raises on its own pre-check (defense in depth).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import Column, MetaData, String, Table, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError

from src.shared.types import BindingId, ConnectionId, TenantId

from ..domain.errors import BindingConflict
from ..domain.models import BindingStatus, Reseller, TenantConnectionBinding

if TYPE_CHECKING:
    from sqlalchemy.engine import Row
    from sqlalchemy.orm import Session, sessionmaker

_metadata = MetaData()

tenant_connection_bindings_table = Table(
    "tenant_connection_bindings",
    _metadata,
    Column("binding_id", String, primary_key=True),
    Column("tenant_id", String, nullable=False),
    Column("connection_id", String, nullable=False),
    Column("erp_customer_id", String, nullable=False),
    Column("status", String, nullable=False),
)

resellers_table = Table(
    "resellers",
    _metadata,
    Column("tenant_id", String, primary_key=True),
    Column("name", String, nullable=False),
)


def _to_model(row: Row) -> TenantConnectionBinding:
    return TenantConnectionBinding(
        binding_id=BindingId(row.binding_id),
        tenant_id=TenantId(row.tenant_id),
        connection_id=ConnectionId(row.connection_id),
        erp_customer_id=row.erp_customer_id,
        status=BindingStatus(row.status),
    )


class PostgresBindingRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def add(self, binding: TenantConnectionBinding) -> None:
        session = self._session_factory()
        try:
            session.execute(
                tenant_connection_bindings_table.insert().values(
                    binding_id=str(binding.binding_id),
                    tenant_id=str(binding.tenant_id),
                    connection_id=str(binding.connection_id),
                    erp_customer_id=binding.erp_customer_id,
                    status=binding.status.value,
                )
            )
            session.commit()
        except IntegrityError as exc:
            session.rollback()
            if getattr(exc.orig, "pgcode", None) == "23505":  # unique_violation only — FK
                raise BindingConflict(  # violations (e.g. unknown connection_id) are a real error
                    f"binding for tenant/connection or connection/customer "
                    f"already exists: {exc.orig}"
                ) from exc
            raise
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def get(self, binding_id: BindingId) -> TenantConnectionBinding | None:
        session = self._session_factory()
        try:
            row = session.execute(
                select(tenant_connection_bindings_table).where(
                    tenant_connection_bindings_table.c.binding_id == str(binding_id)
                )
            ).first()
        finally:
            session.close()
        return _to_model(row) if row is not None else None

    def update(self, binding: TenantConnectionBinding) -> None:
        session = self._session_factory()
        try:
            session.execute(
                tenant_connection_bindings_table.update()
                .where(tenant_connection_bindings_table.c.binding_id == str(binding.binding_id))
                .values(status=binding.status.value)
            )
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def find_by_tenant_and_connection(
        self, tenant_id: TenantId, connection_id: ConnectionId
    ) -> TenantConnectionBinding | None:
        session = self._session_factory()
        try:
            row = session.execute(
                select(tenant_connection_bindings_table).where(
                    tenant_connection_bindings_table.c.tenant_id == str(tenant_id),
                    tenant_connection_bindings_table.c.connection_id == str(connection_id),
                )
            ).first()
        finally:
            session.close()
        return _to_model(row) if row is not None else None

    def find_by_connection_and_customer(
        self, connection_id: ConnectionId, erp_customer_id: str
    ) -> TenantConnectionBinding | None:
        session = self._session_factory()
        try:
            row = session.execute(
                select(tenant_connection_bindings_table).where(
                    tenant_connection_bindings_table.c.connection_id == str(connection_id),
                    tenant_connection_bindings_table.c.erp_customer_id == erp_customer_id,
                )
            ).first()
        finally:
            session.close()
        return _to_model(row) if row is not None else None

    def list_all(self) -> list[TenantConnectionBinding]:
        session = self._session_factory()
        try:
            rows = session.execute(select(tenant_connection_bindings_table)).all()
        finally:
            session.close()
        return [_to_model(row) for row in rows]


class PostgresResellerRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def upsert(self, tenant_id: TenantId, name: str) -> None:
        session = self._session_factory()
        try:
            stmt = pg_insert(resellers_table).values(tenant_id=str(tenant_id), name=name)
            stmt = stmt.on_conflict_do_update(index_elements=["tenant_id"], set_={"name": name})
            session.execute(stmt)
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def get(self, tenant_id: TenantId) -> Reseller | None:
        session = self._session_factory()
        try:
            row = session.execute(
                select(resellers_table).where(resellers_table.c.tenant_id == str(tenant_id))
            ).first()
        finally:
            session.close()
        if row is None:
            return None
        return Reseller(tenant_id=TenantId(row.tenant_id), name=row.name)

    def list_all(self) -> list[Reseller]:
        session = self._session_factory()
        try:
            rows = session.execute(select(resellers_table)).all()
        finally:
            session.close()
        return [Reseller(tenant_id=TenantId(row.tenant_id), name=row.name) for row in rows]
