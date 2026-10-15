from __future__ import annotations

import pytest

from src.modules.integration.mapping.application.service import MappingService
from src.modules.integration.mapping.application.suggestion_service import (
    SampleRequestSuggestionService,
)
from src.modules.integration.mapping.domain.errors import ConnectionNotFound, ErpTypeNotEligible
from src.modules.integration.mapping.domain.request_suggestion import SuggestedSampleRequest
from src.modules.integration.mapping.infrastructure.memory import (
    InMemoryCanonicalSchemaRepository,
    InMemoryMappingJobRepository,
    StubAdapterRunLauncher,
    StubSampleRequestSuggester,
)
from src.modules.reference.connections.domain.models import ErpConnection
from src.modules.reference.connections.infrastructure.memory import InMemoryConnectionRepository
from src.shared.erp_probe import StubErpProbe
from src.shared.secrets import EnvSecretStore
from src.shared.types import ConnectionId

_CSV = "field,description\norder_id,The order id\ncustomer_name,Who placed it\n"


def _service_with_connection(
    *, has_adapter=lambda _erp_type: False
) -> tuple[SampleRequestSuggestionService, str]:
    connections = InMemoryConnectionRepository()
    connection_id = ConnectionId("conn_shopify_1")
    connections.add(
        ErpConnection(
            connection_id=connection_id,
            erp_type="SHOPIFY",
            instance_label="Shopify store",
            base_url="http://erp.example.invalid",
            credentials={},
            secret_ref="env:UNUSED",
            auth_type="NONE",
        )
    )
    mapping_service = MappingService(
        InMemoryMappingJobRepository(),
        InMemoryCanonicalSchemaRepository(),
        StubAdapterRunLauncher(),
        StubErpProbe(),
        EnvSecretStore(),
        connections,
        has_adapter,
    )
    service = SampleRequestSuggestionService(mapping_service, StubSampleRequestSuggester())
    return service, str(connection_id)


def test_suggest_returns_the_offline_stub_suggestions_grounded_in_the_csv() -> None:
    service, connection_id = _service_with_connection()
    suggestions = service.suggest(connection_id=connection_id, canonical_fields_csv=_CSV)
    assert suggestions == [
        SuggestedSampleRequest(label="orders", method="GET", path="/orders?limit=5"),
        SuggestedSampleRequest(label="customers", method="GET", path="/customers?limit=5"),
    ]


def test_suggest_rejects_a_connection_whose_erp_type_already_has_an_adapter() -> None:
    service, connection_id = _service_with_connection(has_adapter=lambda _t: True)
    with pytest.raises(ErpTypeNotEligible):
        service.suggest(connection_id=connection_id, canonical_fields_csv=_CSV)


def test_suggest_rejects_an_unknown_connection() -> None:
    service, _ = _service_with_connection()
    with pytest.raises(ConnectionNotFound):
        service.suggest(connection_id="conn_nope", canonical_fields_csv=_CSV)
