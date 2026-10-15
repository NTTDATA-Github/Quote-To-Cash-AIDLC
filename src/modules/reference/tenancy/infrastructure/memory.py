"""In-memory binding repository that enforces the uniqueness invariants."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..domain.models import Reseller

if TYPE_CHECKING:
    from src.shared.types import BindingId, ConnectionId, TenantId

    from ..domain.models import TenantConnectionBinding


class InMemoryBindingRepository:
    def __init__(self) -> None:
        self._by_id: dict[BindingId, TenantConnectionBinding] = {}

    def add(self, binding: TenantConnectionBinding) -> None:
        self._by_id[binding.binding_id] = binding

    def get(self, binding_id: BindingId) -> TenantConnectionBinding | None:
        return self._by_id.get(binding_id)

    def update(self, binding: TenantConnectionBinding) -> None:
        self._by_id[binding.binding_id] = binding

    def find_by_tenant_and_connection(
        self, tenant_id: TenantId, connection_id: ConnectionId
    ) -> TenantConnectionBinding | None:
        return next(
            (
                b
                for b in self._by_id.values()
                if b.tenant_id == tenant_id and b.connection_id == connection_id
            ),
            None,
        )

    def find_by_connection_and_customer(
        self, connection_id: ConnectionId, erp_customer_id: str
    ) -> TenantConnectionBinding | None:
        return next(
            (
                b
                for b in self._by_id.values()
                if b.connection_id == connection_id and b.erp_customer_id == erp_customer_id
            ),
            None,
        )

    def list_all(self) -> list[TenantConnectionBinding]:
        return list(self._by_id.values())


class InMemoryResellerRepository:
    def __init__(self) -> None:
        self._by_tenant: dict[TenantId, Reseller] = {}

    def upsert(self, tenant_id: TenantId, name: str) -> None:
        self._by_tenant[tenant_id] = Reseller(tenant_id=tenant_id, name=name)

    def get(self, tenant_id: TenantId) -> Reseller | None:
        return self._by_tenant.get(tenant_id)

    def list_all(self) -> list[Reseller]:
        return list(self._by_tenant.values())
