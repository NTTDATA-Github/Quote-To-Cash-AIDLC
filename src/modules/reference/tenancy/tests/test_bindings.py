from __future__ import annotations

import pytest

from src.modules.reference.tenancy.application.service import BindingService
from src.modules.reference.tenancy.domain.attribution import resolve_tenant_for_customer
from src.modules.reference.tenancy.domain.errors import BindingConflict, BindingNotFound
from src.modules.reference.tenancy.domain.events import (
    BINDING_CREATED,
    BINDING_REMOVED,
    BINDING_VERIFIED,
)
from src.modules.reference.tenancy.domain.models import BindingStatus
from src.modules.reference.tenancy.infrastructure.memory import InMemoryBindingRepository
from src.shared.messaging.facts import CollectingFactPublisher
from src.shared.types import BindingId, ConnectionId, TenantId


def _service() -> BindingService:
    return BindingService(InMemoryBindingRepository(), CollectingFactPublisher())


def test_create_then_verify_binding() -> None:
    svc = _service()
    b = svc.create_binding(
        tenant_id=TenantId("tnt_a"), connection_id=ConnectionId("conn_1"), erp_customer_id="C-1"
    )
    assert b.binding_id.startswith("bind_")
    assert not b.is_verified
    verified = svc.verify_binding(b.binding_id)
    assert verified.is_verified


def test_create_verify_remove_each_publish_a_fact() -> None:
    svc = _service()
    facts: CollectingFactPublisher = svc._facts  # type: ignore[attr-defined]
    b = svc.create_binding(
        tenant_id=TenantId("tnt_a"), connection_id=ConnectionId("conn_1"), erp_customer_id="C-1"
    )
    svc.verify_binding(b.binding_id)
    svc.remove_binding(b.binding_id)

    types = [f.event_type for f in facts.published]
    assert types == [BINDING_CREATED, BINDING_VERIFIED, BINDING_REMOVED]
    for fact in facts.published:
        assert fact.payload["binding_id"] == str(b.binding_id)
        assert fact.tenant_id == "tnt_a"


def test_reseller_cannot_bind_same_connection_twice() -> None:
    svc = _service()
    svc.create_binding(
        tenant_id=TenantId("tnt_a"), connection_id=ConnectionId("conn_1"), erp_customer_id="C-1"
    )
    with pytest.raises(BindingConflict):
        svc.create_binding(
            tenant_id=TenantId("tnt_a"), connection_id=ConnectionId("conn_1"), erp_customer_id="C-2"
        )


def test_erp_customer_cannot_map_to_two_tenants() -> None:
    svc = _service()
    svc.create_binding(
        tenant_id=TenantId("tnt_a"), connection_id=ConnectionId("conn_1"), erp_customer_id="C-1"
    )
    with pytest.raises(BindingConflict):
        svc.create_binding(
            tenant_id=TenantId("tnt_b"), connection_id=ConnectionId("conn_1"), erp_customer_id="C-1"
        )


def test_verify_missing_binding_raises() -> None:
    with pytest.raises(BindingNotFound):
        _service().verify_binding(BindingId("bind_missing"))


def test_attribution_only_through_verified_binding() -> None:
    svc = _service()
    b = svc.create_binding(
        tenant_id=TenantId("tnt_a"), connection_id=ConnectionId("conn_1"), erp_customer_id="C-1"
    )
    assert resolve_tenant_for_customer(b) is None  # not verified yet -> not attributable
    svc.verify_binding(b.binding_id)
    assert resolve_tenant_for_customer(b) == TenantId("tnt_a")
    assert resolve_tenant_for_customer(None) is None


def test_re_linking_after_a_removal_creates_a_new_row_and_keeps_the_old_one() -> None:
    repo = InMemoryBindingRepository()
    svc = BindingService(repo, CollectingFactPublisher())
    first = svc.create_binding(
        tenant_id=TenantId("tnt_a"), connection_id=ConnectionId("conn_1"), erp_customer_id="C-1"
    )
    svc.remove_binding(first.binding_id)

    again = svc.create_binding(
        tenant_id=TenantId("tnt_a"), connection_id=ConnectionId("conn_1"), erp_customer_id="C-2"
    )

    assert again.binding_id != first.binding_id  # a new record, not an overwrite of history
    assert again.erp_customer_id == "C-2"
    assert again.status is BindingStatus.TO_VERIFY
    old = repo.get(first.binding_id)
    assert old is not None
    assert old.status is BindingStatus.REMOVED
    assert old.erp_customer_id == "C-1"


def test_removed_link_does_not_block_its_customer_from_another_reseller() -> None:
    svc = _service()
    old = svc.create_binding(
        tenant_id=TenantId("tnt_a"), connection_id=ConnectionId("conn_1"), erp_customer_id="C-1"
    )
    svc.remove_binding(old.binding_id)

    new = svc.create_binding(
        tenant_id=TenantId("tnt_b"), connection_id=ConnectionId("conn_1"), erp_customer_id="C-1"
    )

    assert new.tenant_id == TenantId("tnt_b")
    assert new.status is BindingStatus.TO_VERIFY


def test_active_link_still_blocks_a_second_one_for_the_same_pair() -> None:
    svc = _service()
    svc.create_binding(
        tenant_id=TenantId("tnt_a"), connection_id=ConnectionId("conn_1"), erp_customer_id="C-1"
    )
    with pytest.raises(BindingConflict):
        svc.create_binding(
            tenant_id=TenantId("tnt_a"), connection_id=ConnectionId("conn_1"), erp_customer_id="C-9"
        )
