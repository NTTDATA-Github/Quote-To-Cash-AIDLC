"""BindingService — create and verify tenant↔connection bindings (operator-facing).

Enforces the two uniqueness rules that guarantee cross-tenant isolation:
  - a reseller has at most one binding per connection
  - an ERP customer maps to at most one reseller
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from src.shared.messaging.facts import FactPublisher, make_fact
from src.shared.types import BindingId, ConnectionId, TenantId, generate_id

from ..domain.errors import BindingConflict, BindingNotFound
from ..domain.events import BINDING_CREATED, BINDING_REMOVED, BINDING_VERIFIED
from ..domain.models import BindingStatus, TenantConnectionBinding

if TYPE_CHECKING:
    from .ports import BindingRepository


class BindingService:
    def __init__(self, repository: BindingRepository, facts: FactPublisher) -> None:
        self._repository = repository
        self._facts = facts

    def create_binding(
        self, *, tenant_id: TenantId, connection_id: ConnectionId, erp_customer_id: str
    ) -> TenantConnectionBinding:
        # Only active links count: a removed link is history, so a new link is a new row.
        if self._repository.find_by_tenant_and_connection(tenant_id, connection_id) is not None:
            raise BindingConflict(
                f"tenant '{tenant_id}' already has a binding to connection '{connection_id}'"
            )
        if (
            self._repository.find_by_connection_and_customer(connection_id, erp_customer_id)
            is not None
        ):
            raise BindingConflict(
                f"customer '{erp_customer_id}' in connection '{connection_id}' "
                "is already bound to a tenant"
            )
        binding = TenantConnectionBinding(
            binding_id=BindingId(generate_id("bind")),
            tenant_id=tenant_id,
            connection_id=connection_id,
            erp_customer_id=erp_customer_id,
            status=BindingStatus.TO_VERIFY,
        )
        self._repository.add(binding)
        self._publish(binding, BINDING_CREATED)
        return binding

    def verify_binding(self, binding_id: BindingId) -> TenantConnectionBinding:
        binding = self._repository.get(binding_id)
        if binding is None:
            raise BindingNotFound(str(binding_id))
        binding.status = BindingStatus.VERIFIED
        self._repository.update(binding)
        self._publish(binding, BINDING_VERIFIED)
        return binding

    def remove_binding(self, binding_id: BindingId) -> TenantConnectionBinding:
        """Status change, not a delete: the row stays so historical orders still resolve their
        routing. `is_bound` and customer lookups already treat any non-VERIFIED status as
        unbound, so this takes effect immediately. The unique rules apply only to active rows
        (migration 0019), so the same reseller can link the same connection again later, as a
        new row."""
        binding = self._repository.get(binding_id)
        if binding is None:
            raise BindingNotFound(str(binding_id))
        binding.status = BindingStatus.REMOVED
        self._repository.update(binding)
        self._publish(binding, BINDING_REMOVED)
        return binding

    def _publish(self, binding: TenantConnectionBinding, event_type: str) -> None:
        self._facts.publish(
            make_fact(
                stream_id=str(binding.binding_id),
                aggregate_type="Binding",
                event_type=event_type,
                tenant_id=str(binding.tenant_id),
                payload={
                    "binding_id": str(binding.binding_id),
                    "tenant_id": str(binding.tenant_id),
                    "connection_id": str(binding.connection_id),
                    "erp_customer_id": binding.erp_customer_id,
                    "status": binding.status.value,
                },
            )
        )
