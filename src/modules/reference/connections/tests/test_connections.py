from __future__ import annotations

import pytest

from src.modules.reference.connections.application.service import ConnectionService
from src.modules.reference.connections.domain.errors import ConnectionNotFound
from src.modules.reference.connections.domain.events import (
    CONNECTION_PAUSED,
    CONNECTION_REGISTERED,
    CONNECTION_RESUMED,
)
from src.modules.reference.connections.domain.models import ConnectionStatus
from src.modules.reference.connections.infrastructure.memory import InMemoryConnectionRepository
from src.shared.erp_probe import StubErpProbe
from src.shared.messaging.facts import CollectingFactPublisher
from src.shared.secrets import EnvSecretStore
from src.shared.types import ConnectionId


def _service() -> ConnectionService:
    return ConnectionService(
        InMemoryConnectionRepository(),
        CollectingFactPublisher(),
        EnvSecretStore(),
        StubErpProbe(),
    )


def test_register_creates_active_connection_with_prefixed_id() -> None:
    svc = _service()
    conn = svc.register(
        erp_type="ODOO",
        instance_label="Odoo EU-1",
        base_url="http://odoo:8069",
        credentials={"database": "odoo", "username": "admin"},
        secret="raw-secret-eu1",
    )
    assert conn.connection_id.startswith("conn_")
    assert conn.status is ConnectionStatus.ACTIVE
    assert conn.is_active
    assert svc.get(conn.connection_id) is conn


def test_register_pause_resume_each_publish_a_fact_without_leaking_secrets() -> None:
    svc = _service()
    facts: CollectingFactPublisher = svc._facts  # type: ignore[attr-defined]
    conn = svc.register(
        erp_type="ODOO",
        instance_label="Odoo EU-1",
        base_url="http://odoo:8069",
        credentials={"database": "odoo", "username": "admin"},
        secret="raw-secret-eu1",
    )
    svc.pause(conn.connection_id)
    svc.resume(conn.connection_id)

    types = [f.event_type for f in facts.published]
    assert types == [CONNECTION_REGISTERED, CONNECTION_PAUSED, CONNECTION_RESUMED]
    for fact in facts.published:
        assert fact.payload["connection_id"] == str(conn.connection_id)
        assert "secret_ref" not in fact.payload
        assert "username" not in fact.payload


def test_secret_is_generated_into_a_reference_not_stored_raw() -> None:
    secrets = EnvSecretStore()
    svc = ConnectionService(
        InMemoryConnectionRepository(), CollectingFactPublisher(), secrets, StubErpProbe()
    )
    conn = svc.register(
        erp_type="ODOO",
        instance_label="Odoo US-1",
        base_url="https://odoo-us.example",
        credentials={"database": "odoo_us", "username": "api"},
        secret="raw-secret-us1",
    )
    # secret_ref is a pointer; no plaintext password field exists on the model
    assert conn.secret_ref == f"erp-connection/{conn.connection_id}"
    assert secrets.get_secret(conn.secret_ref) == "raw-secret-us1"
    assert not hasattr(conn, "password")


def test_test_endpoint_probes_a_registered_connection() -> None:
    svc = _service()
    conn = svc.register(
        erp_type="SHOPIFY",
        instance_label="Shopify store",
        base_url="https://shopify.example",
        credentials={},
        secret=None,
    )
    sample = svc.test_endpoint(conn.connection_id, path="/orders")
    # StubErpProbe never dials out — it returns a canned sample, proving the wiring
    # (auth built from the stored connection, single request, one sample back).
    assert sample.error is None
    assert sample.text is not None


def test_test_endpoint_raises_for_an_unknown_connection() -> None:
    svc = _service()
    with pytest.raises(ConnectionNotFound):
        svc.test_endpoint(ConnectionId("conn_nope"))


def test_erp_type_is_normalized() -> None:
    conn = _service().register(
        erp_type="  shopify  ",
        instance_label="Shopify store",
        base_url="https://shopify.example",
        credentials={},
        secret="tok",
    )
    assert conn.erp_type == "SHOPIFY"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("instance_label", "   "),
        ("erp_type", "   "),
        ("base_url", "not-a-url"),
        ("base_url", "ftp://shopify.example"),
        ("base_url", ""),
    ],
)
def test_register_rejects_a_blank_or_malformed_field(field: str, value: str) -> None:
    """A typo in any of these free-typed fields must fail loudly at registration, not
    sit silently until the first probe or delivery against it fails instead."""
    kwargs = {
        "erp_type": "SHOPIFY",
        "instance_label": "Shopify store",
        "base_url": "https://shopify.example",
        "credentials": {},
        "secret": "tok",
    }
    kwargs[field] = value
    with pytest.raises(ValueError):
        _service().register(**kwargs)


def test_register_rejects_an_unknown_auth_type() -> None:
    with pytest.raises(ValueError):
        _service().register(
            erp_type="SHOPIFY",
            instance_label="Shopify store",
            base_url="https://shopify.example",
            credentials={},
            secret="tok",
            auth_type="BEARER_TOKEM",
        )
