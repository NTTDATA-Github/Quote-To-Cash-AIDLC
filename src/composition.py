"""Composition root — the one place the object graph is wired.

Bridges modules to each other's ports (bindings, connection resolution) and selects
infrastructure by `settings.profile`:
- "memory": in-memory bus + event store, for local dev/tests (no infra),
- "postgres": PostgresEventStore + Postgres repos/projection store + real/stub Odoo
  adapter + Secrets Manager. The repo publishes nothing itself (PostgresEventStore writes
  the outbox row in the same transaction as the event); the outbox relay and SQS consumers
  (worker, item C) do the async delivery. `order_processor` / `delivery_handler` /
  `order_projector` are exposed on the container so the worker can wire the same handler
  instances into `SqsConsumerRunner`s without re-deriving the object graph.

Kept out of the domain: this module is allowed to import everything; nothing imports it
except the api/worker hosts.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from src.modules.integration.erp.application.delivery import DeliveryHandler
from src.modules.integration.erp.application.ports import (
    ErpAdapter,
    ErpInvoice,
    ErpShipment,
    ErpTarget,
    UnknownErpType,
)
from src.modules.integration.erp.application.reconcile import ReconcileSweeper
from src.modules.integration.erp.infrastructure.registry import build_adapter_registry
from src.modules.integration.erp.infrastructure.stub_adapter import StubErpAdapter
from src.modules.integration.mapping.application.processing import process_pending_jobs
from src.modules.integration.mapping.application.service import MappingService
from src.modules.integration.mapping.application.suggestion_service import (
    SampleRequestSuggestionService,
)
from src.modules.integration.mapping.infrastructure.agent_launcher import HttpAdapterRunLauncher
from src.modules.integration.mapping.infrastructure.llm_proposer import LlmMappingProposer
from src.modules.integration.mapping.infrastructure.memory import (
    InMemoryCanonicalSchemaRepository,
    InMemoryMappingJobRepository,
    StubAdapterRunLauncher,
    StubMappingProposer,
    StubSampleRequestSuggester,
)
from src.modules.integration.mapping.infrastructure.postgres import (
    PostgresCanonicalSchemaRepository,
    PostgresMappingJobRepository,
)
from src.modules.integration.mapping.infrastructure.request_suggester import (
    LlmSampleRequestSuggester,
)
from src.modules.integration.webhooks_inbound.application.ingress import InboundWebhookService
from src.modules.integration.webhooks_inbound.infrastructure.memory import (
    InMemoryDedupStore,
    InMemoryEventInbox,
    InMemoryOrderLocator,
)
from src.modules.integration.webhooks_inbound.infrastructure.postgres import (
    PostgresDedupStore,
    PostgresEventInbox,
    PostgresOrderLocator,
)
from src.modules.integration.webhooks_outbound.application.dispatch import WebhookDispatchService
from src.modules.integration.webhooks_outbound.domain.models import DISPATCHABLE_EVENT_TYPES
from src.modules.integration.webhooks_outbound.infrastructure.http_sender import HttpWebhookSender
from src.modules.integration.webhooks_outbound.infrastructure.memory import (
    InMemoryWebhookDeliveryRepository,
    InMemoryWebhookEndpointRepository,
)
from src.modules.integration.webhooks_outbound.infrastructure.postgres import (
    PostgresWebhookDeliveryRepository,
    PostgresWebhookEndpointRepository,
)
from src.modules.reference.connections.infrastructure.memory import InMemoryConnectionRepository
from src.modules.reference.connections.infrastructure.postgres import PostgresConnectionRepository
from src.modules.reference.tenancy.infrastructure.memory import (
    InMemoryBindingRepository,
    InMemoryResellerRepository,
)
from src.modules.reference.tenancy.infrastructure.postgres import (
    PostgresBindingRepository,
    PostgresResellerRepository,
)
from src.modules.sales.invoicing.application.service import InvoiceService
from src.modules.sales.invoicing.domain.aggregate import Invoice
from src.modules.sales.ordering.application.adapters import (
    OrderCommandAdapter,
    OrderReaderAdapter,
    StatusApplier,
)
from src.modules.sales.ordering.application.fulfillment_consumer import OrderFulfillmentConsumer
from src.modules.sales.ordering.application.order_service import OrderService
from src.modules.sales.ordering.application.processing import OrderProcessor
from src.modules.sales.ordering.domain.aggregate import Order
from src.modules.sales.ordering.projections.postgres_store import PostgresOrderProjectionStore
from src.modules.sales.ordering.projections.projector import OrderProjector
from src.modules.sales.ordering.projections.store import OrderProjectionStore
from src.modules.sales.quoting.application.service import QuoteService
from src.modules.sales.quoting.infrastructure.memory import (
    InMemoryQuoteRepository,
    InMemorySubsidiaryRepository,
    InMemorySubsidiaryRouteRepository,
)
from src.modules.sales.quoting.infrastructure.postgres import (
    PostgresQuoteRepository,
    PostgresSubsidiaryRepository,
    PostgresSubsidiaryRouteRepository,
)
from src.modules.sales.shipment.application.service import ShipmentService
from src.modules.sales.shipment.domain.aggregate import Shipment
from src.shared.config import Settings, get_settings
from src.shared.erp_probe import ErpProbe, GenericErpProbe, StubErpProbe
from src.shared.eventsourcing import EventSourcedRepository, EventStore, InMemoryEventStore
from src.shared.identity import (
    CognitoIdentityProvider,
    EntraIdentityProvider,
    HeaderStubIdentityProvider,
    IdentityProvider,
    KeycloakIdentityProvider,
)
from src.shared.identity.cognito import issuer_url
from src.shared.llm import (
    AnthropicLlmClient,
    AzureFoundryLlmClient,
    BedrockLlmClient,
    OpenAiLlmClient,
)
from src.shared.messaging import InMemoryMessageBus
from src.shared.messaging.facts import BusFactPublisher, FactPublisher, OutboxFactPublisher
from src.shared.persistence.engine import get_session_factory
from src.shared.persistence.event_store import PostgresEventStore
from src.shared.secrets import EnvSecretStore, SecretStore
from src.shared.secrets.aws import SecretsManagerSecretStore
from src.shared.secrets.azure import KeyVaultSecretStore

if TYPE_CHECKING:
    from collections.abc import Callable

    from src.modules.integration.mapping.application.ports import (
        LlmClient,
        MappingJobRepository,
        MappingProposer,
    )
    from src.modules.integration.webhooks_outbound.application.ports import (
        WebhookDeliveryRepository,
        WebhookEndpointRepository,
    )
    from src.modules.reference.connections.application.ports import ConnectionRepository
    from src.modules.reference.tenancy.application.ports import (
        BindingRepository,
        ResellerRepository,
    )
    from src.modules.sales.quoting.application.ports import (
        QuoteRepository,
        SubsidiaryRepository,
        SubsidiaryRouteRepository,
    )
    from src.shared.types import ConnectionId, TenantId


log = logging.getLogger(__name__)


# --- bridge adapters: other modules' repos -> the ports ordering/integration expect ---
class TenancyBindingQuery:
    def __init__(self, bindings: BindingRepository) -> None:
        self._bindings = bindings

    def is_bound(self, tenant_id: TenantId, connection_id: ConnectionId) -> bool:
        binding = self._bindings.find_by_tenant_and_connection(tenant_id, connection_id)
        return binding is not None and binding.is_verified


class TenancyCustomerDirectory:
    """Resolves a reseller's ERP customer id for a connection, from the binding — the id
    the order is sent to the ERP as (FR-A1). Operator-only data; stays off reseller views."""

    def __init__(self, bindings: BindingRepository) -> None:
        self._bindings = bindings

    def erp_customer_id_for(self, tenant_id: TenantId, connection_id: ConnectionId) -> str | None:
        binding = self._bindings.find_by_tenant_and_connection(tenant_id, connection_id)
        return binding.erp_customer_id if binding is not None else None


class ConnectionsResolver:
    def __init__(self, connections: ConnectionRepository, secrets: SecretStore) -> None:
        self._connections = connections
        self._secrets = secrets

    def resolve(self, connection_id: ConnectionId) -> ErpTarget | None:
        connection = self._connections.get(connection_id)
        if connection is None or not connection.is_active:
            return None
        return ErpTarget(
            erp_type=connection.erp_type,
            base_url=connection.base_url,
            credentials=dict(connection.credentials),
            secret=self._secrets.get_secret(connection.secret_ref),
        )


class ConnectionWebhookSecretResolver:
    """Resolves the per-connection inbound-webhook secret — `webhook_secret_ref`, which
    is deliberately NOT the same secret as the ERP login credential (`secret_ref`); see
    `ErpConnection.webhook_secret_ref`. `None` (no secret configured, or resolution
    failed) means this connection hasn't onboarded webhooks yet — every webhook for it
    is rejected UNAUTHORIZED, which is correct: it falls back to the reconcile sweeper."""

    def __init__(self, connections: ConnectionRepository, secrets: SecretStore) -> None:
        self._connections = connections
        self._secrets = secrets

    def secret_for(self, connection_id: ConnectionId) -> str | None:
        connection = self._connections.get(connection_id)
        if connection is None or connection.webhook_secret_ref is None:
            return None
        try:
            return self._secrets.get_secret(connection.webhook_secret_ref)
        except Exception:
            return None


@dataclass
class Container:
    settings: Settings
    order_service: OrderService
    projections: OrderProjectionStore | PostgresOrderProjectionStore
    ingress: InboundWebhookService
    bus: InMemoryMessageBus | None  # None in the postgres profile (no synchronous bus)
    drain: Callable[[], None]  # memory: bus.run_until_empty; postgres: no-op, worker drains
    connections: ConnectionRepository
    bindings: BindingRepository
    resellers: ResellerRepository
    order_processor: OrderProcessor
    delivery_handler: DeliveryHandler
    order_projector: OrderProjector
    reconcile_sweeper: ReconcileSweeper | None  # None in the memory profile (worker-only)
    identity: IdentityProvider
    event_store: (
        EventStore  # raw event access — the operator "order events" dev view reads this directly
    )
    webhook_endpoints: WebhookEndpointRepository
    webhook_deliveries: WebhookDeliveryRepository
    webhook_dispatcher: WebhookDispatchService
    # exposed so WebhookEndpointService (GraphQL layer) can generate+store signing secrets
    secrets: SecretStore
    # the ERP probe used both by MappingService (onboarding sample fetch) and by
    # ConnectionService's "test endpoint" action (GraphQL layer) — stub offline, generic
    # (stdlib HTTP) in postgres
    erp_probe: ErpProbe
    # catalog/connections/tenancy publish notifications through this (src/shared/messaging/facts.py)
    facts: FactPublisher
    shipment_service: ShipmentService
    invoice_service: InvoiceService
    # ordering side of the shipment/invoice saga (ADR-0018) — the `order-fulfillment`
    # consumer; exposed so the worker can wire it into an SqsConsumerRunner
    order_fulfillment_consumer: OrderFulfillmentConsumer
    orders: EventSourcedRepository[
        Order
    ]  # exposed so GraphQL can read fulfillment_status/invoice_status (derived, aggregate-only)
    quote_service: QuoteService
    quotes: QuoteRepository
    subsidiaries: SubsidiaryRepository
    subsidiary_routes: SubsidiaryRouteRepository
    # ERP field-mapping proposer (operator AdminOps "ERP mapping" tab). `mapping_jobs` and
    # `mapping_proposer` are exposed so the worker's `mapping` role can run the LLM off the
    # request path; `mapping_process_pending` processes inline in the memory profile (with
    # a deterministic stub proposer) and is a no-op in postgres (the worker does it).
    mapping_service: MappingService
    mapping_jobs: MappingJobRepository
    mapping_proposer: MappingProposer
    mapping_process_pending: Callable[[], int]
    # Suggests which record kinds/paths to pull live during onboarding (separate from
    # mapping_proposer — a different, synchronous LLM call, answered straight from the
    # request path since it's cheap, not handed to the worker).
    sample_request_suggestion: SampleRequestSuggestionService
    # ADR-0021's derived `hasAdapter` fact — read by the GraphQL layer per-connection and
    # by MappingService's per-erp_type dedupe guard (ADR-0022); never stored.
    has_adapter: Callable[[str], bool]


def _matched_lines(order: Order, items: list) -> list[dict[str, str]]:
    """Map an ERP document's SKUs onto this order's line ids. An unknown SKU is skipped."""
    line_for: dict[str, str] = {}
    for line in order.lines:
        line_for.setdefault(line.product_key, line.line_id)
    return [
        {"line_id": line_for[item.product_key], "quantity": item.quantity}
        for item in items
        if item.product_key in line_for
    ]


def _erp_shipment_sync(orders: EventSourcedRepository[Order], shipments: ShipmentService):
    """Turn ERP deliveries into shipment records. A repeat poll of the same picking is a no-op."""

    def sync(order_id: str, erp_shipments: list[ErpShipment]) -> None:
        order = orders.get(order_id)
        for erp_shipment in erp_shipments:
            lines = _matched_lines(order, list(erp_shipment.lines))
            if not lines:
                continue
            shipments.record_once(
                shipment_id=f"shp_{erp_shipment.erp_shipment_id}",
                order_id=order_id,
                lines=lines,
                carrier=erp_shipment.carrier,
                tracking_number=erp_shipment.tracking_number,
                proof_of_delivery=erp_shipment.proof_of_delivery,
                tenant_id=str(order.tenant_id),
            )

    return sync


def _webhook_refresh(connections, adapter_for, sync_shipments, sync_invoices):
    """A webhook names the order. Shipments and invoices are read from the ERP, same as
    the sweep."""

    def refresh(connection_id: ConnectionId, erp_order_id: str, order_id: str) -> None:
        target = connections.resolve(connection_id)
        if target is None:
            return
        adapter = adapter_for(target.erp_type)
        sync_shipments(order_id, adapter.fetch_shipments(target, erp_order_id))
        sync_invoices(order_id, adapter.fetch_invoices(target, erp_order_id))

    return refresh


def _erp_invoice_sync(orders: EventSourcedRepository[Order], invoices: InvoiceService):
    """Turn ERP invoices into invoice records. A repeat poll of the same invoice is a no-op."""

    def sync(order_id: str, erp_invoices: list[ErpInvoice]) -> None:
        order = orders.get(order_id)
        for erp_invoice in erp_invoices:
            lines = _matched_lines(order, list(erp_invoice.lines))
            if not lines:
                continue
            invoices.record_once(
                invoice_id=f"inv_{erp_invoice.erp_invoice_id}",
                order_id=order_id,
                lines=lines,
                erp_invoice_id=erp_invoice.number or erp_invoice.erp_invoice_id,
                tenant_id=str(order.tenant_id),
            )

    return sync


def build_container(settings: Settings | None = None) -> Container:
    settings = settings or get_settings()
    if settings.profile == "postgres":
        return _build_postgres_container(settings)
    return _build_memory_container(settings)


def _build_memory_container(settings: Settings) -> Container:
    event_store = InMemoryEventStore()
    bus = InMemoryMessageBus()
    repo: EventSourcedRepository[Order] = EventSourcedRepository(event_store, Order, publisher=bus)
    # Same event store as Order — one `events` table in Postgres too, differentiated by
    # aggregate_type + stream_id, not a separate store per aggregate type.
    # Shipment/Invoice publish their events to the bus (ADR-0018); the ordering saga
    # consumer below reacts to them and bumps the order's quantity scores — no shared
    # write transaction.
    shipment_service = ShipmentService(EventSourcedRepository(event_store, Shipment, publisher=bus))
    invoice_service = InvoiceService(EventSourcedRepository(event_store, Invoice, publisher=bus))
    order_fulfillment_consumer = OrderFulfillmentConsumer(repo)

    connections = InMemoryConnectionRepository()
    bindings = InMemoryBindingRepository()
    resellers = InMemoryResellerRepository()
    quotes = InMemoryQuoteRepository()
    subsidiaries = InMemorySubsidiaryRepository()
    subsidiary_routes = InMemorySubsidiaryRouteRepository()
    quote_service = QuoteService(quotes, subsidiaries, subsidiary_routes)
    secrets: SecretStore = EnvSecretStore()

    projections = OrderProjectionStore()
    locator = InMemoryOrderLocator()

    erp_adapter: ErpAdapter = StubErpAdapter()

    def adapter_for(_erp_type):
        return erp_adapter

    processor = OrderProcessor(repo, TenancyBindingQuery(bindings))
    delivery = DeliveryHandler(
        connections=ConnectionsResolver(connections, secrets),
        orders_read=OrderReaderAdapter(projections, TenancyCustomerDirectory(bindings)),
        orders_cmd=OrderCommandAdapter(repo),
        adapter_for=adapter_for,
    )
    projector = OrderProjector(projections, locator=locator)

    webhook_endpoints = InMemoryWebhookEndpointRepository()
    webhook_deliveries = InMemoryWebhookDeliveryRepository()
    webhook_dispatcher = WebhookDispatchService(
        endpoints=webhook_endpoints,
        deliveries=webhook_deliveries,
        secrets=secrets,
        sender=HttpWebhookSender(),
        orders=projections,
    )

    bus.subscribe("projections", projector.handle)
    bus.subscribe("order-processing", processor.handle, event_types={"OrderSubmitted"})
    bus.subscribe("order-delivery", delivery.handle, event_types={"OrderReadyForDelivery"})
    bus.subscribe(
        "order-fulfillment",
        order_fulfillment_consumer.handle,
        event_types={"ShipmentRecorded", "InvoiceRecorded"},
    )
    bus.subscribe(
        "webhook-dispatch", webhook_dispatcher.handle, event_types=set(DISPATCHABLE_EVENT_TYPES)
    )

    ingress = InboundWebhookService(
        secrets=ConnectionWebhookSecretResolver(connections, secrets),
        dedup=InMemoryDedupStore(),
        inbox=InMemoryEventInbox(),
        locator=locator,
        order_status=StatusApplier(repo),
        refresh=_webhook_refresh(
            ConnectionsResolver(connections, secrets),
            adapter_for,
            _erp_shipment_sync(repo, shipment_service),
            _erp_invoice_sync(repo, invoice_service),
        ),
    )

    erp_probe: ErpProbe = StubErpProbe()
    mapping_jobs: MappingJobRepository = InMemoryMappingJobRepository()
    mapping_proposer: MappingProposer = StubMappingProposer()
    mapping_service = MappingService(
        mapping_jobs,
        InMemoryCanonicalSchemaRepository(),
        StubAdapterRunLauncher(),
        erp_probe,
        secrets,
        connections,
        # Memory profile: nothing pre-adapted, so the onboarding flow stays testable
        lambda _erp_type: False,
    )
    sample_request_suggestion = SampleRequestSuggestionService(
        mapping_service, StubSampleRequestSuggester()
    )

    return Container(
        settings=settings,
        order_service=OrderService(repo),
        projections=projections,
        ingress=ingress,
        bus=bus,
        drain=bus.run_until_empty,
        connections=connections,
        bindings=bindings,
        resellers=resellers,
        order_processor=processor,
        delivery_handler=delivery,
        order_projector=projector,
        reconcile_sweeper=None,
        identity=HeaderStubIdentityProvider(),
        event_store=event_store,
        webhook_endpoints=webhook_endpoints,
        webhook_deliveries=webhook_deliveries,
        webhook_dispatcher=webhook_dispatcher,
        secrets=secrets,
        erp_probe=erp_probe,
        facts=BusFactPublisher(bus),
        shipment_service=shipment_service,
        invoice_service=invoice_service,
        order_fulfillment_consumer=order_fulfillment_consumer,
        orders=repo,
        quote_service=quote_service,
        quotes=quotes,
        subsidiaries=subsidiaries,
        subsidiary_routes=subsidiary_routes,
        mapping_service=mapping_service,
        mapping_jobs=mapping_jobs,
        mapping_proposer=mapping_proposer,
        # memory profile has no worker — process the just-submitted job inline (offline stub)
        mapping_process_pending=lambda: process_pending_jobs(mapping_jobs, mapping_proposer),
        sample_request_suggestion=sample_request_suggestion,
        has_adapter=lambda _erp_type: False,
    )


def _resolve_adapter_for(settings: Settings) -> Callable[[str], ErpAdapter]:
    """`erp_adapter_mode="stub"` overrides every ERP type with the deterministic stub
    (local dev/testing, no real HTTP). Otherwise dispatch through the adapter registry —
    see `integration/infrastructure/registry.py` for how a new ERP gets added here."""
    if settings.erp_adapter_mode == "stub":
        stub = StubErpAdapter()
        return lambda _erp_type: stub

    registry = build_adapter_registry(settings)

    def resolve(erp_type: str) -> ErpAdapter:
        adapter = registry.get(erp_type)
        if adapter is None:
            raise UnknownErpType(erp_type)
        return adapter

    return resolve


def _has_adapter_for(settings: Settings) -> Callable[[str], bool]:
    """ADR-0021's `hasAdapter` — always reflects the *real* adapter registry, regardless
    of `erp_adapter_mode`. Deliberately independent of `_resolve_adapter_for`'s stub
    override: that mode fakes *delivery* for local testing, but mapping-eligibility
    (ADR-0022) should still ask "does real code exist", not "are we pretending it does"."""
    registry = build_adapter_registry(settings)
    return lambda erp_type: erp_type in registry


def _resolve_identity_provider(settings: Settings) -> IdentityProvider:
    """Real verification once the active cloud's identity env vars are configured; the
    header stub until then (so the postgres profile stays usable for local dev against
    floci — with a *live* Odoo/worker/SQS pipeline but no identity provider set up yet —
    without hard-failing container construction). ADR-0023: `cloud_provider` picks Cognito
    vs. Entra; within either, setting the relevant env vars turns on real verification."""
    if settings.cloud_provider == "azure":
        # Keycloak takes priority: it's the IdentityProvider actually standing today (no
        # real Entra External ID tenant exists — Entra app creation is blocked in this
        # sandbox, see ADR-0023). Entra stays available for whenever that changes.
        if settings.keycloak_issuer:
            return KeycloakIdentityProvider(
                issuer=settings.keycloak_issuer,
                client_id=settings.keycloak_client_id,
            )
        if settings.entra_tenant_id and settings.entra_client_id:
            return EntraIdentityProvider(
                tenant_id=settings.entra_tenant_id,
                client_id=settings.entra_client_id,
                tenant_claim_name=settings.entra_tenant_claim_name,
            )
        log.warning(
            "KEYCLOAK_ISSUER/ENTRA_TENANT_ID+ENTRA_CLIENT_ID not set — "
            "using the header stub, not real auth"
        )
        return HeaderStubIdentityProvider()

    if not settings.cognito_user_pool_id or not settings.cognito_client_id:
        log.warning(
            "COGNITO_USER_POOL_ID/COGNITO_CLIENT_ID not set — using the header stub, not real auth"
        )
        return HeaderStubIdentityProvider()
    issuer = issuer_url(
        aws_endpoint_url=settings.aws_endpoint_url,
        aws_region=settings.aws_region,
        user_pool_id=settings.cognito_user_pool_id,
    )
    return CognitoIdentityProvider(
        user_pool_id=settings.cognito_user_pool_id,
        client_id=settings.cognito_client_id,
        issuer=issuer,
        resource_server_id=settings.cognito_resource_server_id,
    )


def _resolve_secret_store(settings: Settings) -> SecretStore:
    """ADR-0023: which cloud's secret store backs the `SecretStore` port."""
    if settings.cloud_provider == "azure":
        assert settings.azure_key_vault_uri, "AZURE_KEY_VAULT_URI required for CLOUD_PROVIDER=azure"
        return KeyVaultSecretStore(
            settings.azure_key_vault_uri,
            managed_identity_client_id=settings.azure_managed_identity_client_id,
        )
    return SecretsManagerSecretStore(
        endpoint_url=settings.aws_endpoint_url, region_name=settings.aws_region
    )


def _llm_client(settings: Settings, secrets: SecretStore) -> LlmClient:
    """ADR-0023: which cloud's LLM client backs `MappingProposer`/sample-request
    suggestions. The API key is never a plaintext env var — same "secrets never
    in plaintext" rule as every other credential (SECURITY-12, `secrets/store.py`) —
    it's read from Key Vault through the same `SecretStore` port everything else uses.

    Cloud-agnostic provider selection: `mapping_llm_provider` (if set) overrides the
    general `llm_provider`. When not set, defaults to foundry (if available), else
    anthropic (azure), else bedrock (aws).
    """
    provider = settings.mapping_llm_provider
    if not provider:
        provider = settings.llm_provider
    if not provider:
        provider = (
            "foundry"
            if settings.foundry_endpoint
            else ("anthropic" if settings.cloud_provider == "azure" else "bedrock")
        )

    if provider == "openai":
        if not settings.foundry_endpoint:
            raise RuntimeError(
                "FOUNDRY_ENDPOINT required for mapping_llm_provider=openai "
                "(e.g., https://<region>.api.foundry.azure.com/...)"
            )
        api_key = settings.foundry_api_key or secrets.get_secret("foundry-api-key")
        return OpenAiLlmClient(
            settings.foundry_endpoint,
            api_key=api_key,
            model_id=settings.mapping_openai_model,
        )
    elif provider == "foundry":
        if not settings.foundry_endpoint:
            raise RuntimeError(
                "FOUNDRY_ENDPOINT required for llm_provider=foundry "
                "(e.g., https://<region>.api.foundry.azure.com/...)"
            )
        api_key = settings.foundry_api_key or secrets.get_secret("foundry-api-key")
        return AzureFoundryLlmClient(
            settings.foundry_endpoint,
            api_key=api_key,
            model_id=settings.mapping_anthropic_model,
        )
    elif provider == "anthropic":
        return AnthropicLlmClient(
            settings.mapping_anthropic_model, api_key=secrets.get_secret("anthropic-api-key")
        )
    elif provider == "bedrock":
        return BedrockLlmClient(settings.mapping_bedrock_model_id, settings.aws_region)
    else:
        raise ValueError(
            f"unknown LLM_PROVIDER '{provider}' — valid: bedrock, anthropic, foundry, openai"
        )


def _build_postgres_container(settings: Settings) -> Container:
    session_factory = get_session_factory(settings.database_url)
    event_store = PostgresEventStore(session_factory)
    # PostgresEventStore.append writes the outbox row in the same transaction as the
    # event — the repo must not also publish synchronously, or events would be delivered
    # twice (once here, once by the relay). outbox=None, publisher=None is deliberate.
    repo: EventSourcedRepository[Order] = EventSourcedRepository(event_store, Order)
    # Same reasoning as the memory profile: one `events` table, one store, differentiated
    # by aggregate_type + stream_id. Shipment and Invoice publish via the outbox
    # (PostgresEventStore writes the outbox row); the relay
    # delivers them to the `order-fulfillment` queue, whose consumer bumps the order's
    # scores (ADR-0018). No publisher here, same as the Order repo.
    shipment_service = ShipmentService(EventSourcedRepository(event_store, Shipment))
    invoice_service = InvoiceService(EventSourcedRepository(event_store, Invoice))
    order_fulfillment_consumer = OrderFulfillmentConsumer(repo)

    connections = PostgresConnectionRepository(session_factory)
    bindings = PostgresBindingRepository(session_factory)
    resellers = PostgresResellerRepository(session_factory)
    quotes = PostgresQuoteRepository(session_factory)
    subsidiaries = PostgresSubsidiaryRepository(session_factory)
    subsidiary_routes = PostgresSubsidiaryRouteRepository(session_factory)
    quote_service = QuoteService(quotes, subsidiaries, subsidiary_routes)
    secrets: SecretStore = _resolve_secret_store(settings)
    identity = _resolve_identity_provider(settings)

    projections = PostgresOrderProjectionStore(session_factory)
    locator = PostgresOrderLocator(session_factory)

    adapter_for = _resolve_adapter_for(settings)

    connections_resolver = ConnectionsResolver(connections, secrets)
    status_applier = StatusApplier(repo)

    processor = OrderProcessor(repo, TenancyBindingQuery(bindings))
    delivery = DeliveryHandler(
        connections=connections_resolver,
        orders_read=OrderReaderAdapter(projections, TenancyCustomerDirectory(bindings)),
        orders_cmd=OrderCommandAdapter(repo),
        adapter_for=adapter_for,
    )
    projector = OrderProjector(projections, locator=locator)

    ingress = InboundWebhookService(
        secrets=ConnectionWebhookSecretResolver(connections, secrets),
        dedup=PostgresDedupStore(session_factory),
        inbox=PostgresEventInbox(session_factory),
        locator=locator,
        order_status=status_applier,
        refresh=_webhook_refresh(
            connections_resolver,
            adapter_for,
            _erp_shipment_sync(repo, shipment_service),
            _erp_invoice_sync(repo, invoice_service),
        ),
    )

    order_service = OrderService(repo)

    def discover(connection_id: ConnectionId) -> list[str]:
        target = connections_resolver.resolve(connection_id)
        if target is None:
            return []
        fetch = getattr(adapter_for(target.erp_type), "fetch_partner_orders", None)
        if fetch is None:
            return []
        ids: list[str] = []
        for binding in bindings.list_all():
            if str(binding.connection_id) != str(connection_id) or not binding.is_verified:
                continue
            try:
                found = fetch(target, binding.erp_customer_id)
            except Exception:
                log.exception(
                    "could not list ERP orders connection=%s partner=%s",
                    connection_id,
                    binding.erp_customer_id,
                )
                continue
            for erp_order in found:
                subsidiary_id = quote_service.find_subsidiary(
                    str(connection_id), erp_order.erp_company_id
                )
                if not subsidiary_id:
                    log.info(
                        "skip ERP order connection=%s order=%s company=%s: no subsidiary",
                        connection_id,
                        erp_order.erp_order_id,
                        erp_order.erp_company_id,
                    )
                    continue
                adopted = order_service.observe_erp_order(
                    tenant_id=binding.tenant_id,
                    connection_id=str(connection_id),
                    erp_order_id=erp_order.erp_order_id,
                    client_reference=erp_order.client_reference,
                    lines=erp_order.lines,
                    subsidiary_id=subsidiary_id,
                )
                if adopted is not None:
                    ids.append(erp_order.erp_order_id)
        return ids

    reconcile_sweeper = ReconcileSweeper(
        connections=connections_resolver,
        adapter_for=adapter_for,
        locator=locator,
        order_status=status_applier,
        sync_shipments=_erp_shipment_sync(repo, shipment_service),
        sync_invoices=_erp_invoice_sync(repo, invoice_service),
        discover=discover,
    )

    webhook_endpoints = PostgresWebhookEndpointRepository(session_factory)
    webhook_deliveries = PostgresWebhookDeliveryRepository(session_factory)
    webhook_dispatcher = WebhookDispatchService(
        endpoints=webhook_endpoints,
        deliveries=webhook_deliveries,
        secrets=secrets,
        sender=HttpWebhookSender(),
        orders=projections,
    )

    erp_probe: ErpProbe = GenericErpProbe(
        secrets, allow_private_addresses=settings.erp_probe_allow_private_addresses
    )
    mapping_jobs: MappingJobRepository = PostgresMappingJobRepository(session_factory)
    mapping_proposer: MappingProposer = LlmMappingProposer(_llm_client(settings, secrets))
    has_adapter = _has_adapter_for(settings)
    mapping_service = MappingService(
        mapping_jobs,
        PostgresCanonicalSchemaRepository(session_factory),
        HttpAdapterRunLauncher(settings.agent_service_url),
        erp_probe,
        secrets,
        connections,
        has_adapter,
    )
    sample_request_suggestion = SampleRequestSuggestionService(
        mapping_service, LlmSampleRequestSuggester(_llm_client(settings, secrets))
    )

    return Container(
        settings=settings,
        order_service=order_service,
        projections=projections,
        ingress=ingress,
        bus=None,
        drain=lambda: None,
        connections=connections,
        bindings=bindings,
        resellers=resellers,
        order_processor=processor,
        delivery_handler=delivery,
        order_projector=projector,
        reconcile_sweeper=reconcile_sweeper,
        identity=identity,
        event_store=event_store,
        webhook_endpoints=webhook_endpoints,
        webhook_deliveries=webhook_deliveries,
        webhook_dispatcher=webhook_dispatcher,
        secrets=secrets,
        erp_probe=erp_probe,
        facts=OutboxFactPublisher(session_factory),
        shipment_service=shipment_service,
        invoice_service=invoice_service,
        order_fulfillment_consumer=order_fulfillment_consumer,
        orders=repo,
        quote_service=quote_service,
        quotes=quotes,
        subsidiaries=subsidiaries,
        subsidiary_routes=subsidiary_routes,
        mapping_service=mapping_service,
        mapping_jobs=mapping_jobs,
        mapping_proposer=mapping_proposer,
        # the `mapping` worker role runs the LLM off the request path — not inline here
        mapping_process_pending=lambda: 0,
        sample_request_suggestion=sample_request_suggestion,
        has_adapter=has_adapter,
    )
