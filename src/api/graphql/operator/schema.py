"""Operator GraphQL schema. Requires the OPERATOR role; may expose ERP identity.

Admin mutations here are thin wrappers around already-built application services
(`ConnectionService`, `BindingService`, `QuoteService`, fulfillment services) — this
schema holds no new business logic.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import strawberry
from strawberry.extensions import QueryDepthLimiter

from src.modules.integration.mapping.domain.canonical_order_schema import (
    build_canonical_order_fields_csv,
)
from src.modules.integration.mapping.domain.errors import (
    CanonicalSchemaNotFound,
    ConnectionNotFound,
    EmptyCanonicalSchema,
    ErpTypeNotEligible,
    MappingJobNotFound,
    MappingNotReady,
    NoCanonicalFields,
    ProbeFailed,
)
from src.modules.reference.connections.application.service import ConnectionService
from src.modules.reference.connections.domain.errors import (
    ConnectionNotFound as ConnectionNotFoundRef,
)
from src.modules.reference.tenancy.application.service import BindingService
from src.shared.erp_probe import SampleRequestSpec
from src.shared.types import BindingId, ConnectionId, TenantId

from .types import (
    AdapterRunType,
    AuthConfigInput,
    BindingType,
    CanonicalSchemaType,
    ConnectionType,
    ErpRouteType,
    MappingEntryType,
    MappingJobType,
    MoneyType,
    NotificationType,
    OperatorOrder,
    OperatorOrderLineType,
    OperatorPartiesType,
    OperatorTimelineEntryType,
    OrderEventType,
    ProbeSampleType,
    ResellerType,
    SampleFileInput,
    SampleRequestInput,
    SubsidiaryType,
    SuggestedRequestType,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from strawberry.types import Info

    from src.modules.integration.mapping.domain.models import (
        AdapterRunResult,
        MappingJob,
    )
    from src.modules.integration.mapping.domain.request_suggestion import SuggestedSampleRequest
    from src.modules.integration.webhooks_outbound.application.ports import (
        WebhookEndpointRepository,
    )
    from src.modules.reference.connections.domain.models import ErpConnection
    from src.modules.reference.tenancy.domain.models import Reseller, TenantConnectionBinding
    from src.modules.sales.ordering.projections.read_models import OperatorOrderView
    from src.modules.sales.quoting.domain.models import Subsidiary
    from src.shared.erp_probe import ProbeSample
    from src.shared.money import Money

    from ..context import GraphQLContext


def _money_to_gql(money: Money | None) -> MoneyType | None:
    return None if money is None else MoneyType(amount=str(money.amount), currency=money.currency)


def _order_to_gql(view: OperatorOrderView) -> OperatorOrder:
    return OperatorOrder(
        order_id=view.order_id,
        tenant_id=view.tenant_id,
        client_reference=view.client_reference,
        status=view.status,
        owning_connection_id=view.owning_connection_id,
        erp_order_id=view.erp_order_id,
        lines=[
            OperatorOrderLineType(
                product_key=line.product_key,
                quantity=line.quantity,
                unit_of_measure=line.unit_of_measure,
                line_id=line.line_id,
                kind=line.kind,
                unit_price=_money_to_gql(line.unit_price),
                line_total=_money_to_gql(line.line_total),
                shipped_quantity=line.shipped_quantity,
                delivered_quantity=line.delivered_quantity,
                invoiced_quantity=line.invoiced_quantity,
                scheduled_date=line.scheduled_date,
            )
            for line in view.lines
        ],
        timeline=[
            OperatorTimelineEntryType(status=t.status, occurred_at=t.occurred_at)
            for t in view.timeline
        ],
        subtotal=_money_to_gql(view.subtotal),
        fulfillment_status=view.fulfillment_status,
        delivery_status=view.delivery_status,
        invoice_status=view.invoice_status,
        parties=OperatorPartiesType(
            end_customer_name=view.parties.end_customer_name,
            ship_to=view.parties.ship_to,
            subsidiary_id=view.parties.subsidiary_id,
            quote_id=view.parties.quote_id,
        ),
    )


def _connection_to_gql(
    connection: ErpConnection,
    has_adapter: Callable[[str], bool],
    mapping_status: Callable[[ErpConnection], str],
) -> ConnectionType:
    return ConnectionType(
        connection_id=str(connection.connection_id),
        erp_type=connection.erp_type,
        instance_label=connection.instance_label,
        base_url=connection.base_url,
        credentials=dict(connection.credentials),
        status=connection.status.value,
        secret_ref=connection.secret_ref,
        has_webhook_secret=connection.webhook_secret_ref is not None,
        has_adapter=has_adapter(connection.erp_type),
        mapping_status=mapping_status(connection),
    )


def _binding_to_gql(binding: TenantConnectionBinding) -> BindingType:
    return BindingType(
        binding_id=str(binding.binding_id),
        tenant_id=str(binding.tenant_id),
        connection_id=str(binding.connection_id),
        erp_customer_id=binding.erp_customer_id,
        status=binding.status.value,
    )


def _reseller_to_gql(reseller: Reseller, endpoints: WebhookEndpointRepository) -> ResellerType:
    return ResellerType(
        tenant_id=str(reseller.tenant_id),
        name=reseller.name,
        webhook_urls=[e.url for e in endpoints.list_by_tenant(reseller.tenant_id)],
    )


def _company_to_gql(company: Subsidiary) -> SubsidiaryType:
    return SubsidiaryType(
        subsidiary_id=company.subsidiary_id,
        name=company.name,
        country=company.country,
        language=company.language,
    )


def _mapping_job_to_gql(job: MappingJob) -> MappingJobType:
    return MappingJobType(
        job_id=job.job_id,
        erp_name=job.erp_name,
        status=job.status.value,
        mapping=[
            MappingEntryType(
                erp_field=e.erp_field,
                canonical_field=e.canonical_field,
                sample_data=e.sample_data,
                confidence=e.confidence,
            )
            for e in (job.result or [])
        ],
        error=job.error,
        adapter_run_id=job.adapter_run_id,
        created_at=job.created_at.isoformat(),
        schema_name=job.schema_name,
        sample_files=list(job.sample_exports),
    )


def _probe_sample_to_gql(sample: ProbeSample) -> ProbeSampleType:
    return ProbeSampleType(label=sample.label, text=sample.text, error=sample.error)


def _sample_requests_from_input(requests: list[SampleRequestInput]) -> list[SampleRequestSpec]:
    return [
        SampleRequestSpec(
            label=r.label, method=r.method, path=r.path, query_params=dict(r.query_params)
        )
        for r in requests
    ]


def _suggested_request_to_gql(suggestion: SuggestedSampleRequest) -> SuggestedRequestType:
    return SuggestedRequestType(
        label=suggestion.label, method=suggestion.method, path=suggestion.path
    )


def _adapter_run_to_gql(run: AdapterRunResult) -> AdapterRunType:
    return AdapterRunType(status=run.status, branch=run.branch, pr_url=run.pr_url, error=run.error)


@strawberry.type
class Query:
    @strawberry.field
    def order(self, info: Info[GraphQLContext, None], order_id: str) -> OperatorOrder | None:
        ctx = info.context
        ctx.require_role("OPERATOR")
        view = ctx.container.projections.get_operator_view(order_id)
        return _order_to_gql(view) if view else None

    @strawberry.field
    def orders(self, info: Info[GraphQLContext, None]) -> list[OperatorOrder]:
        """Every order, across every tenant — operator debugging/visibility, never
        reseller-reachable (the reseller schema's `orders` stays tenant-scoped)."""
        ctx = info.context
        ctx.require_role("OPERATOR")
        return [_order_to_gql(v) for v in ctx.container.projections.list_operator_views()]

    @strawberry.field
    def order_events(self, info: Info[GraphQLContext, None], order_id: str) -> list[OrderEventType]:
        """The raw event stream for one order, in order — the event-sourcing/developer
        view. Reads `events` directly, not a projection."""
        ctx = info.context
        ctx.require_role("OPERATOR")
        events = ctx.container.event_store.load(order_id)
        return [
            OrderEventType(
                event_type=e.event_type,
                version=e.version,
                occurred_at=e.occurred_at.isoformat(),
                correlation_id=e.correlation_id,
                payload=dict(e.payload),
            )
            for e in events
        ]

    @strawberry.field
    def notifications(self, info: Info[GraphQLContext, None]) -> list[NotificationType]:
        """Every webhook sent to a reseller, across every reseller."""
        ctx = info.context
        ctx.require_role("OPERATOR")
        return [
            NotificationType(
                delivery_id=d.delivery_id,
                tenant_id=str(d.tenant_id),
                endpoint_id=str(d.endpoint_id),
                order_id=d.order_id,
                event_type=d.event_type,
                occurred_at=d.occurred_at.isoformat(),
                status=d.status.value,
                attempts=d.attempts,
                last_response=d.last_response,
            )
            for d in ctx.container.webhook_deliveries.list_all()
        ]

    @strawberry.field
    def connections(self, info: Info[GraphQLContext, None]) -> list[ConnectionType]:
        ctx = info.context
        ctx.require_role("OPERATOR")
        connections = ctx.container.connections.list_all()
        mapping_status = ctx.container.mapping_service.connection_mapping_status
        return [
            _connection_to_gql(c, ctx.container.has_adapter, mapping_status) for c in connections
        ]

    @strawberry.field
    def bindings(self, info: Info[GraphQLContext, None]) -> list[BindingType]:
        ctx = info.context
        ctx.require_role("OPERATOR")
        return [_binding_to_gql(b) for b in ctx.container.bindings.list_all()]

    @strawberry.field
    def resellers(self, info: Info[GraphQLContext, None]) -> list[ResellerType]:
        ctx = info.context
        ctx.require_role("OPERATOR")
        return [
            _reseller_to_gql(r, ctx.container.webhook_endpoints)
            for r in ctx.container.resellers.list_all()
        ]

    @strawberry.field
    def subsidiaries(self, info: Info[GraphQLContext, None]) -> list[SubsidiaryType]:
        ctx = info.context
        ctx.require_role("OPERATOR")
        return [_company_to_gql(c) for c in ctx.container.quote_service.list_subsidiaries()]

    @strawberry.field
    def erp_route(
        self, info: Info[GraphQLContext, None], subsidiary_id: str
    ) -> ErpRouteType | None:
        ctx = info.context
        ctx.require_role("OPERATOR")
        connection_id = ctx.container.quote_service.get_erp_route(subsidiary_id)
        if connection_id is None:
            return None
        return ErpRouteType(
            connection_id=connection_id,
            erp_company_id=ctx.container.quote_service.get_erp_company_id(subsidiary_id),
        )

    # --- ERP field-mapping proposer ---
    @strawberry.field
    def canonical_schemas(self, info: Info[GraphQLContext, None]) -> list[CanonicalSchemaType]:
        """The registered canonical field lists a mapping can be proposed against."""
        ctx = info.context
        ctx.require_role("OPERATOR")
        service = ctx.container.mapping_service
        return [
            CanonicalSchemaType(name=name, field_count=service.field_count(name))
            for name in service.list_schemas()
        ]

    @strawberry.field
    def canonical_order_schema(self, info: Info[GraphQLContext, None]) -> str:
        """The "our order fields" CSV an operator used to have to type by hand — derived
        live from the real adapter contract (`ErpPartnerOrder` et al. in
        `integration.erp`). Add a field there and it's here on the next request; no
        file to maintain, no button to press."""
        ctx = info.context
        ctx.require_role("OPERATOR")
        return build_canonical_order_fields_csv()

    @strawberry.field
    def mapping_jobs(self, info: Info[GraphQLContext, None]) -> list[MappingJobType]:
        """Every proposal, newest first. Several ERPs can be in flight at once."""
        ctx = info.context
        ctx.require_role("OPERATOR")
        return [_mapping_job_to_gql(job) for job in ctx.container.mapping_service.list_jobs()]

    @strawberry.field
    def mappable_connections(self, info: Info[GraphQLContext, None]) -> list[ConnectionType]:
        """What the Mapping page's connection picker offers (ADR-0021/0022): connections
        whose `erp_type` has no adapter yet and no mapping job already in flight or
        approved for it."""
        ctx = info.context
        ctx.require_role("OPERATOR")
        mapping_status = ctx.container.mapping_service.connection_mapping_status
        return [
            _connection_to_gql(c, ctx.container.has_adapter, mapping_status)
            for c in ctx.container.mapping_service.eligible_connections()
        ]

    @strawberry.field
    def mapping_job(self, info: Info[GraphQLContext, None], job_id: str) -> MappingJobType | None:
        """Poll a submitted proposal job. `status` goes PENDING -> PROCESSING -> DONE /
        FAILED; `mapping` is populated once DONE."""
        ctx = info.context
        ctx.require_role("OPERATOR")
        job = ctx.container.mapping_service.get_job(job_id)
        return _mapping_job_to_gql(job) if job is not None else None

    @strawberry.field
    def adapter_run(self, info: Info[GraphQLContext, None], job_id: str) -> AdapterRunType | None:
        """Poll the adapter-codegen run started by `approveMapping`. Null until approved."""
        ctx = info.context
        ctx.require_role("OPERATOR")
        try:
            run = ctx.container.mapping_service.get_adapter_run(job_id)
        except MappingJobNotFound as e:
            raise Exception(f"mapping job not found: {e}") from e
        return _adapter_run_to_gql(run) if run is not None else None


@strawberry.type
class Mutation:
    @strawberry.mutation
    def register_connection(
        self,
        info: Info[GraphQLContext, None],
        erp_type: str,
        instance_label: str,
        base_url: str,
        credentials: strawberry.scalars.JSON,
        auth: AuthConfigInput,
        webhook_secret_ref: str | None = None,
    ) -> ConnectionType:
        """`credentials` is the generic, adapter-interpreted bag (ADR-0012) — e.g. Odoo's
        `database`/`username`. `auth` is read only by the onboarding probe for a
        connection with no adapter yet (ADR-0021): `auth.params` merge into the same
        `credentials` bag, `auth.authType` is stored alongside it, and `auth.secret` is
        the raw credential (password/API key/token) — generated into Secrets Manager
        here, never hand-pasted as a `secretRef`."""
        ctx = info.context
        ctx.require_role("OPERATOR")
        service = ConnectionService(
            ctx.container.connections,
            ctx.container.facts,
            ctx.container.secrets,
            ctx.container.erp_probe,
        )
        merged_credentials = {str(k): str(v) for k, v in dict(credentials).items()}
        merged_credentials.update({str(k): str(v) for k, v in dict(auth.params).items()})
        try:
            connection = service.register(
                erp_type=erp_type,
                instance_label=instance_label,
                base_url=base_url,
                credentials=merged_credentials,
                secret=auth.secret,
                auth_type=auth.auth_type,
                webhook_secret_ref=webhook_secret_ref,
            )
        except ValueError as e:
            raise Exception(str(e)) from e
        mapping_status = ctx.container.mapping_service.connection_mapping_status
        return _connection_to_gql(connection, ctx.container.has_adapter, mapping_status)

    @strawberry.mutation
    def create_binding(
        self,
        info: Info[GraphQLContext, None],
        tenant_id: str,
        connection_id: str,
        erp_customer_id: str,
        name: str,
    ) -> BindingType:
        ctx = info.context
        ctx.require_role("OPERATOR")
        service = BindingService(ctx.container.bindings, ctx.container.facts)
        binding = service.create_binding(
            tenant_id=TenantId(tenant_id),
            connection_id=ConnectionId(connection_id),
            erp_customer_id=erp_customer_id,
        )
        ctx.container.resellers.upsert(TenantId(tenant_id), name)
        return _binding_to_gql(binding)

    @strawberry.mutation
    def rename_reseller(
        self, info: Info[GraphQLContext, None], tenant_id: str, name: str
    ) -> ResellerType:
        ctx = info.context
        ctx.require_role("OPERATOR")
        ctx.container.resellers.upsert(TenantId(tenant_id), name)
        reseller = ctx.container.resellers.get(TenantId(tenant_id))
        assert reseller is not None
        return _reseller_to_gql(reseller, ctx.container.webhook_endpoints)

    @strawberry.mutation
    def verify_binding(self, info: Info[GraphQLContext, None], binding_id: str) -> BindingType:
        ctx = info.context
        ctx.require_role("OPERATOR")
        service = BindingService(ctx.container.bindings, ctx.container.facts)
        binding = service.verify_binding(BindingId(binding_id))
        return _binding_to_gql(binding)

    @strawberry.mutation
    def pause_connection(
        self, info: Info[GraphQLContext, None], connection_id: str
    ) -> ConnectionType:
        ctx = info.context
        ctx.require_role("OPERATOR")
        service = ConnectionService(
            ctx.container.connections,
            ctx.container.facts,
            ctx.container.secrets,
            ctx.container.erp_probe,
        )
        connection = service.pause(ConnectionId(connection_id))
        mapping_status = ctx.container.mapping_service.connection_mapping_status
        return _connection_to_gql(connection, ctx.container.has_adapter, mapping_status)

    @strawberry.mutation
    def resume_connection(
        self, info: Info[GraphQLContext, None], connection_id: str
    ) -> ConnectionType:
        ctx = info.context
        ctx.require_role("OPERATOR")
        service = ConnectionService(
            ctx.container.connections,
            ctx.container.facts,
            ctx.container.secrets,
            ctx.container.erp_probe,
        )
        connection = service.resume(ConnectionId(connection_id))
        mapping_status = ctx.container.mapping_service.connection_mapping_status
        return _connection_to_gql(connection, ctx.container.has_adapter, mapping_status)

    @strawberry.mutation
    def rename_connection(
        self, info: Info[GraphQLContext, None], connection_id: str, instance_label: str
    ) -> ConnectionType:
        ctx = info.context
        ctx.require_role("OPERATOR")
        service = ConnectionService(
            ctx.container.connections,
            ctx.container.facts,
            ctx.container.secrets,
            ctx.container.erp_probe,
        )
        try:
            connection = service.rename(ConnectionId(connection_id), instance_label)
        except ValueError as e:
            raise Exception(str(e)) from e
        mapping_status = ctx.container.mapping_service.connection_mapping_status
        return _connection_to_gql(connection, ctx.container.has_adapter, mapping_status)

    @strawberry.mutation
    def test_erp_endpoint(
        self, info: Info[GraphQLContext, None], connection_id: str, path: str = ""
    ) -> ProbeSampleType:
        """Reachability + auth check for an existing connection (ADR-0021): fires one
        request at `path` against its stored base URL and credentials, returning what came
        back (or the ERP's error). Works for any connection, adapter or not — distinct from
        `probeErpSamples`, which gates on mapping eligibility and serves onboarding only."""
        ctx = info.context
        ctx.require_role("OPERATOR")
        service = ConnectionService(
            ctx.container.connections,
            ctx.container.facts,
            ctx.container.secrets,
            ctx.container.erp_probe,
        )
        try:
            sample = service.test_endpoint(ConnectionId(connection_id), path=path)
        except ConnectionNotFoundRef as e:
            raise Exception(str(e)) from e
        return _probe_sample_to_gql(sample)

    @strawberry.mutation
    def remove_binding(self, info: Info[GraphQLContext, None], binding_id: str) -> BindingType:
        ctx = info.context
        ctx.require_role("OPERATOR")
        service = BindingService(ctx.container.bindings, ctx.container.facts)
        return _binding_to_gql(service.remove_binding(BindingId(binding_id)))

    # --- subsidiary + quotes (FR-B / FR-C) ---
    @strawberry.mutation
    def create_subsidiary(
        self, info: Info[GraphQLContext, None], name: str, country: str, language: str
    ) -> SubsidiaryType:
        ctx = info.context
        ctx.require_role("OPERATOR")
        company = ctx.container.quote_service.create_subsidiary(
            name=name, country=country, language=language
        )
        return _company_to_gql(company)

    @strawberry.mutation
    def set_erp_route(
        self,
        info: Info[GraphQLContext, None],
        subsidiary_id: str,
        connection_id: str,
        erp_company_id: str,
    ) -> SubsidiaryType:
        """Which ERP connection this subsidiary uses, and which company id on that
        connection is this subsidiary. The company id is read off the quotation."""
        ctx = info.context
        ctx.require_role("OPERATOR")
        ctx.container.quote_service.set_erp_route(subsidiary_id, connection_id, erp_company_id)
        company = ctx.container.quote_service.get_subsidiary(subsidiary_id)
        assert company is not None
        return _company_to_gql(company)

    @strawberry.mutation
    def set_vendor_date(
        self, info: Info[GraphQLContext, None], order_id: str, line_id: str, vendor_date: str
    ) -> bool:
        """Purchasing bought the line from the maker on `vendor_date` — "scheduled" (FR-E1).
        No Vendor Order document yet (FR-E2)."""
        ctx = info.context
        ctx.require_role("OPERATOR")
        order = ctx.container.orders.get(order_id)
        order.set_vendor_date(line_id, vendor_date)
        ctx.container.orders.save(order)
        ctx.container.drain()
        return True

    # --- ERP field-mapping proposer ---
    @strawberry.mutation
    def register_canonical_schema(
        self, info: Info[GraphQLContext, None], name: str, csv_text: str
    ) -> CanonicalSchemaType:
        """Register (or replace) a canonical field list — a CSV of `field,description`
        rows — reusable by name across many proposal jobs."""
        ctx = info.context
        ctx.require_role("OPERATOR")
        try:
            ctx.container.mapping_service.register_schema(name, csv_text)
        except EmptyCanonicalSchema as e:
            raise Exception(str(e)) from e
        return CanonicalSchemaType(
            name=name, field_count=ctx.container.mapping_service.field_count(name)
        )

    @strawberry.mutation
    def submit_mapping(
        self,
        info: Info[GraphQLContext, None],
        connection_id: str,
        sample_files: list[SampleFileInput],
        schema_name: str | None = None,
        canonical_fields_csv: str | None = None,
    ) -> MappingJobType:
        """Submit an ERP's sample export(s) for a draft mapping against a canonical field
        list (a registered `schemaName` OR an inline `canonicalFieldsCsv`). `connectionId`
        must be one of `mappableConnections` (ADR-0021/0022) — the manual-upload fallback
        for whatever auth the live probe can't handle. Returns the enqueued job; poll
        `mappingJob(jobId)` for the result."""
        ctx = info.context
        ctx.require_role("OPERATOR")
        try:
            job = ctx.container.mapping_service.submit_job(
                connection_id=connection_id,
                sample_files={f.filename: f.content for f in sample_files},
                schema_name=schema_name,
                canonical_fields_csv=canonical_fields_csv,
            )
        except (
            CanonicalSchemaNotFound,
            EmptyCanonicalSchema,
            NoCanonicalFields,
            ConnectionNotFound,
            ErpTypeNotEligible,
            ValueError,
        ) as e:
            raise Exception(str(e)) from e
        # Memory profile has no worker — process inline so the result is ready on the next
        # poll. In the postgres profile this is a no-op; the `mapping` worker role runs it.
        ctx.container.mapping_process_pending()
        refreshed = ctx.container.mapping_service.get_job(job.job_id)
        return _mapping_job_to_gql(refreshed if refreshed is not None else job)

    @strawberry.mutation
    def probe_erp_samples(
        self,
        info: Info[GraphQLContext, None],
        connection_id: str,
        requests: list[SampleRequestInput],
    ) -> list[ProbeSampleType]:
        """Test an already-registered connection before committing to a mapping job
        (ADR-0021): fires each sample request using that connection's stored auth, and
        returns what came back (or the error), with no job created yet."""
        ctx = info.context
        ctx.require_role("OPERATOR")
        try:
            results = ctx.container.mapping_service.probe_samples(
                connection_id=connection_id,
                requests=_sample_requests_from_input(requests),
            )
        except (ConnectionNotFound, ErpTypeNotEligible, ValueError) as e:
            raise Exception(str(e)) from e
        return [_probe_sample_to_gql(s) for s in results]

    @strawberry.mutation
    def suggest_sample_requests(
        self,
        info: Info[GraphQLContext, None],
        connection_id: str,
        schema_name: str | None = None,
        canonical_fields_csv: str | None = None,
    ) -> list[SuggestedRequestType]:
        """An LLM's best guess at which record kinds (and REST paths) to pull live from
        this connection's ERP, grounded in whichever canonical fields were picked above —
        a starting point for "Sample requests", never fired itself. Every suggestion is
        still just a label/method/path the operator sees and can edit before anything
        actually calls out (`probeErpSamples`/`submitMappingFromProbe`)."""
        ctx = info.context
        ctx.require_role("OPERATOR")
        try:
            suggestions = ctx.container.sample_request_suggestion.suggest(
                connection_id=connection_id,
                schema_name=schema_name,
                canonical_fields_csv=canonical_fields_csv,
            )
        except (
            CanonicalSchemaNotFound,
            EmptyCanonicalSchema,
            NoCanonicalFields,
            ConnectionNotFound,
            ErpTypeNotEligible,
            ValueError,
        ) as e:
            raise Exception(str(e)) from e
        return [_suggested_request_to_gql(s) for s in suggestions]

    @strawberry.mutation
    def submit_mapping_from_probe(
        self,
        info: Info[GraphQLContext, None],
        connection_id: str,
        requests: list[SampleRequestInput],
        schema_name: str | None = None,
        canonical_fields_csv: str | None = None,
    ) -> MappingJobType:
        """Probes the connection live, then submits the fetched samples as a mapping job —
        same downstream review/approve flow as `submitMapping`. Raises if any sample
        request failed, since a partial sample set would silently bias the proposal."""
        ctx = info.context
        ctx.require_role("OPERATOR")
        try:
            job = ctx.container.mapping_service.submit_job_from_probe(
                connection_id=connection_id,
                requests=_sample_requests_from_input(requests),
                schema_name=schema_name,
                canonical_fields_csv=canonical_fields_csv,
            )
        except (
            CanonicalSchemaNotFound,
            EmptyCanonicalSchema,
            NoCanonicalFields,
            ConnectionNotFound,
            ErpTypeNotEligible,
            ProbeFailed,
            ValueError,
        ) as e:
            raise Exception(str(e)) from e
        ctx.container.mapping_process_pending()
        refreshed = ctx.container.mapping_service.get_job(job.job_id)
        return _mapping_job_to_gql(refreshed if refreshed is not None else job)

    @strawberry.mutation
    def approve_mapping(self, info: Info[GraphQLContext, None], job_id: str) -> MappingJobType:
        """Approve a reviewed mapping and hand it to the adapter-codegen service. Poll
        `adapterRun(jobId)` for the branch/PR. The mapping is treated as ground truth —
        review it first."""
        ctx = info.context
        ctx.require_role("OPERATOR")
        try:
            job = ctx.container.mapping_service.approve(job_id)
        except MappingJobNotFound as e:
            raise Exception(f"mapping job not found: {e}") from e
        except MappingNotReady as e:
            raise Exception(str(e)) from e
        return _mapping_job_to_gql(job)


def build_operator_schema() -> strawberry.Schema:
    return strawberry.Schema(
        query=Query, mutation=Mutation, extensions=[QueryDepthLimiter(max_depth=10)]
    )
