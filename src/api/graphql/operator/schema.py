"""Operator GraphQL schema. Requires the OPERATOR role; may expose ERP identity.

Admin mutations here are thin wrappers around already-built application services
(`ConnectionService`, `BindingService`, `QuoteService`, fulfillment services) — this
schema holds no new business logic.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

import strawberry
from strawberry.extensions import QueryDepthLimiter

if TYPE_CHECKING:
    # `strawberry.scalars.JSON` is a `NewType` instance, not a type form, so type
    # checkers reject it in annotation position ("expected a type form, got instance
    # of NewType"). Alias it to `Any` for the checker; at runtime it stays the real
    # Strawberry scalar below, so the generated schema keeps its `JSON` scalar.
    JSON = Any
else:
    JSON = strawberry.scalars.JSON

from src.modules.integration.conflicts.application.causes import cause_of
from src.modules.integration.conflicts.domain.categories import LABELS, ConflictCategory
from src.modules.integration.conflicts.domain.models import (
    ConflictExplanationUnavailable,
    ConflictNotFound,
    ConflictStatus,
    OrderConflict,
    SeverityRule,
)
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
from src.modules.integration.webhooks_outbound.application.service import WebhookEndpointService
from src.modules.reference.connections.application.service import ConnectionService
from src.modules.reference.connections.domain.erp_catalog import ERP_CATALOG
from src.modules.reference.connections.domain.errors import (
    ConnectionNotFound as ConnectionNotFoundRef,
)
from src.modules.reference.tenancy.application.service import BindingService
from src.shared.erp_auth import AuthType
from src.shared.erp_probe import SampleRequestSpec
from src.shared.types import BindingId, ConnectionId, OrderId, TenantId, WebhookEndpointId

from .types import (
    AdapterRunType,
    AuthConfigInput,
    BindingType,
    CanonicalSchemaType,
    ConflictExplanationType,
    ConnectionType,
    ErpFieldType,
    ErpRouteType,
    ErpTypeType,
    MappingEntryType,
    MappingJobType,
    MoneyType,
    NotificationType,
    OperatorOrder,
    OperatorOrderLineType,
    OperatorPartiesType,
    OperatorTimelineEntryType,
    OrderConflictType,
    OrderEventType,
    ProbeSampleType,
    ResellerType,
    SampleFileInput,
    SampleRequestInput,
    SeverityRuleType,
    SubsidiaryType,
    SuggestedRequestType,
    WebhookEndpointCreatedType,
    WebhookEndpointType,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from strawberry.types import Info

    from src.modules.integration.conflicts.application.ports import CauseClassifier
    from src.modules.integration.mapping.domain.models import (
        AdapterRunResult,
        MappingJob,
    )
    from src.modules.integration.mapping.domain.request_suggestion import SuggestedSampleRequest
    from src.modules.integration.webhooks_outbound.application.ports import (
        WebhookEndpoint,
        WebhookEndpointRepository,
    )
    from src.modules.reference.connections.domain.models import ErpConnection
    from src.modules.reference.tenancy.domain.models import Reseller, TenantConnectionBinding
    from src.modules.sales.ordering.projections.read_models import OperatorOrderView
    from src.modules.sales.quoting.domain.models import Subsidiary
    from src.shared.erp_probe import ProbeSample
    from src.shared.money import Money

    from ..context import GraphQLContext


logger = logging.getLogger(__name__)


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
        auth_type=connection.auth_type,
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


def _rule_to_gql(rule: SeverityRule) -> SeverityRuleType:
    return SeverityRuleType(
        category=rule.category,
        label=LABELS[ConflictCategory(rule.category)],
        when_rejected=rule.when_rejected.value,
        when_retrying=rule.when_retrying.value,
    )


def _conflict_to_gql(conflict: OrderConflict, classifier: CauseClassifier) -> OrderConflictType:
    return OrderConflictType(
        conflict_id=conflict.conflict_id,
        tenant_id=conflict.tenant_id,
        order_id=conflict.order_id,
        reason_code=conflict.reason_code,
        reason=conflict.reason,
        severity=conflict.severity.value,
        status=conflict.status.value,
        attempts=conflict.attempts,
        opened_at=conflict.opened_at.isoformat(),
        sla_due_at=conflict.sla_due_at.isoformat(),
        resolved_at=conflict.resolved_at.isoformat() if conflict.resolved_at else None,
        resolution_note=conflict.resolution_note,
        category=cause_of(conflict.reason_code, conflict.reason, classifier)[0].value,
        category_source=cause_of(conflict.reason_code, conflict.reason, classifier)[1],
    )


def endpoint_to_gql(endpoint: WebhookEndpoint) -> WebhookEndpointType:
    return WebhookEndpointType(
        endpoint_id=str(endpoint.endpoint_id),
        name=endpoint.name,
        url=endpoint.url,
        event_types=list(endpoint.event_types) if endpoint.event_types is not None else None,
        is_active=endpoint.is_active,
        auth_type=endpoint.auth_type.value,
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
    def webhook_endpoints(
        self, info: Info[GraphQLContext, None], tenant_id: str
    ) -> list[WebhookEndpointType]:
        """Every webhook URL for one reseller, including paused ones."""
        ctx = info.context
        ctx.require_role("OPERATOR")
        return [
            endpoint_to_gql(e)
            for e in ctx.container.webhook_endpoints.list_by_tenant(TenantId(tenant_id))
        ]

    @strawberry.field
    def order_conflicts(
        self, info: Info[GraphQLContext, None], status: str | None = None
    ) -> list[OrderConflictType]:
        """Failed or rejected deliveries, newest first. `status` filters to one state."""
        ctx = info.context
        ctx.require_role("OPERATOR")
        wanted = ConflictStatus(status) if status else None
        return [
            _conflict_to_gql(c, ctx.container.cause_classifier)
            for c in ctx.container.conflicts.list(wanted)
        ]

    @strawberry.field
    def order_conflict(
        self, info: Info[GraphQLContext, None], conflict_id: str
    ) -> OrderConflictType | None:
        ctx = info.context
        ctx.require_role("OPERATOR")
        try:
            return _conflict_to_gql(
                ctx.container.conflicts.get(conflict_id), ctx.container.cause_classifier
            )
        except ConflictNotFound:
            return None

    @strawberry.field
    def conflict_severity_rules(self, info: Info[GraphQLContext, None]) -> list[SeverityRuleType]:
        ctx = info.context
        ctx.require_role("OPERATOR")
        return [_rule_to_gql(r) for r in ctx.container.conflicts.severity_rules()]

    @strawberry.field
    def conflict_explanation(
        self, info: Info[GraphQLContext, None], conflict_id: str
    ) -> ConflictExplanationType:
        """An AI summary of one conflict, from its facts only. Never an error to the operator:
        when no summary can be given, the reason comes back instead."""
        ctx = info.context
        ctx.require_role("OPERATOR")
        try:
            conflict = ctx.container.conflicts.get(conflict_id)
        except ConflictNotFound as e:
            raise Exception(f"no conflict {conflict_id}") from e
        reseller = ctx.container.resellers.get(TenantId(conflict.tenant_id))
        reseller_name = reseller.name if reseller else conflict.tenant_id
        try:
            text = ctx.container.conflict_explainer.explain(conflict, reseller_name)
        except ConflictExplanationUnavailable as e:
            return ConflictExplanationType(text=None, unavailable=str(e))
        except Exception:
            logger.exception("conflict summary failed for %s", conflict_id)
            return ConflictExplanationType(
                text=None,
                unavailable="The summary could not be written right now. Try again in a moment.",
            )
        return ConflictExplanationType(text=text, unavailable=None)

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
    def erp_types(self, info: Info[GraphQLContext, None]) -> list[ErpTypeType]:
        """The ERP types the add-connection form can build, with their fields in plain
        language. Lives in code (domain/erp_catalog.py), not the database."""
        info.context.require_role("OPERATOR")
        return [
            ErpTypeType(
                code=spec.code,
                name=spec.name,
                auth_type=spec.auth_type,
                fields=[
                    ErpFieldType(
                        key=f.key, label=f.label, hint=f.hint, target=f.target, secret=f.secret
                    )
                    for f in spec.fields
                ],
            )
            for spec in ERP_CATALOG
        ]

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
        credentials: JSON,
        auth: AuthConfigInput,
        webhook_secret_ref: str | None = None,
    ) -> ConnectionType:
        """`credentials` is the generic, adapter-interpreted bag (ADR-0012) — e.g. Odoo's
        `database`/`username`. `auth` is read only by the onboarding probe for a
        connection with no adapter yet (ADR-0021): `auth.params` merge into the same
        `credentials` bag, `auth.authType` is stored alongside it, and `auth.secret` is
        the raw credential (password/API key/token) — generated into Key Vault
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
    def register_reseller_webhook(
        self,
        info: Info[GraphQLContext, None],
        tenant_id: str,
        name: str,
        url: str,
        auth_type: str = "NONE",
        auth_params: JSON | None = None,
        auth_secret: str | None = None,
    ) -> WebhookEndpointCreatedType:
        """Adds a webhook URL for a reseller, on the reseller's behalf. The signing secret
        is returned once, here, so the operator can hand it to the reseller. `auth_type`,
        `auth_params` and `auth_secret` describe the credential we send to the URL."""
        ctx = info.context
        ctx.require_role("OPERATOR")
        service = WebhookEndpointService(ctx.container.webhook_endpoints, ctx.container.secrets)
        try:
            endpoint, raw_secret = service.register(
                tenant_id=TenantId(tenant_id),
                name=name,
                url=url,
                event_types=None,
                auth_type=AuthType(auth_type),
                auth_params={str(k): str(v) for k, v in dict(auth_params or {}).items()},
                auth_secret=auth_secret or None,
            )
        except ValueError as e:
            raise Exception(str(e)) from e
        return WebhookEndpointCreatedType(
            endpoint=endpoint_to_gql(endpoint), signing_secret=raw_secret
        )

    @strawberry.mutation
    def set_conflict_severity_rule(
        self,
        info: Info[GraphQLContext, None],
        category: str,
        when_rejected: str,
        when_retrying: str,
    ) -> SeverityRuleType:
        """Changes how urgent one cause is. Applies to conflicts opened from now on."""
        ctx = info.context
        ctx.require_role("OPERATOR")
        try:
            rule = ctx.container.conflicts.set_severity_rule(
                category, when_rejected=when_rejected, when_retrying=when_retrying
            )
        except ValueError as e:
            raise Exception(str(e)) from e
        return _rule_to_gql(rule)

    @strawberry.mutation
    def pause_webhook_endpoint(
        self, info: Info[GraphQLContext, None], tenant_id: str, endpoint_id: str
    ) -> WebhookEndpointType:
        ctx = info.context
        ctx.require_role("OPERATOR")
        service = WebhookEndpointService(ctx.container.webhook_endpoints, ctx.container.secrets)
        return endpoint_to_gql(
            service.pause(WebhookEndpointId(endpoint_id), tenant_id=TenantId(tenant_id))
        )

    @strawberry.mutation
    def resume_webhook_endpoint(
        self, info: Info[GraphQLContext, None], tenant_id: str, endpoint_id: str
    ) -> WebhookEndpointType:
        ctx = info.context
        ctx.require_role("OPERATOR")
        service = WebhookEndpointService(ctx.container.webhook_endpoints, ctx.container.secrets)
        return endpoint_to_gql(
            service.resume(WebhookEndpointId(endpoint_id), tenant_id=TenantId(tenant_id))
        )

    @strawberry.mutation
    def cancel_order(self, info: Info[GraphQLContext, None], order_id: str, reason: str) -> bool:
        ctx = info.context
        ctx.require_role("OPERATOR")
        ctx.container.order_service.cancel_order(OrderId(order_id), reason)
        ctx.container.drain()
        return True

    @strawberry.mutation
    def verify_binding(self, info: Info[GraphQLContext, None], binding_id: str) -> BindingType:
        ctx = info.context
        ctx.require_role("OPERATOR")
        service = BindingService(ctx.container.bindings, ctx.container.facts)
        binding = service.verify_binding(BindingId(binding_id))
        return _binding_to_gql(binding)

    @strawberry.mutation
    def update_connection(
        self,
        info: Info[GraphQLContext, None],
        connection_id: str,
        instance_label: str,
        base_url: str,
        credentials: JSON,
        secret: str | None = None,
    ) -> ConnectionType:
        """Edits a saved connection. A blank or missing `secret` keeps the stored one."""
        ctx = info.context
        ctx.require_role("OPERATOR")
        service = ConnectionService(
            ctx.container.connections,
            ctx.container.facts,
            ctx.container.secrets,
            ctx.container.erp_probe,
        )
        try:
            connection = service.update(
                ConnectionId(connection_id),
                instance_label=instance_label,
                base_url=base_url,
                credentials={str(k): str(v) for k, v in dict(credentials).items()},
                secret=secret or None,
            )
        except ValueError as e:
            raise Exception(str(e)) from e
        mapping_status = ctx.container.mapping_service.connection_mapping_status
        return _connection_to_gql(connection, ctx.container.has_adapter, mapping_status)

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
