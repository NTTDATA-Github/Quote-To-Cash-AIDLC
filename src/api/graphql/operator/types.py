"""Operator GraphQL types — may include ERP identity (operator screens only)."""

from __future__ import annotations

import strawberry


@strawberry.type
class NotificationType:
    delivery_id: str
    tenant_id: str
    endpoint_id: str
    order_id: str
    event_type: str
    occurred_at: str
    status: str
    attempts: int
    last_response: str | None


@strawberry.type
class ErpRouteType:
    connection_id: str
    erp_company_id: str


@strawberry.type
class MoneyType:
    # str, not float (known gap, architect review 2026-10-04): internal Money/TaxRate
    # are Decimal-exact; float can't represent 19.99 exactly, and a client doing its own
    # arithmetic on this field would inherit that error even though every computation
    # inside the platform stays exact end to end.
    amount: str
    currency: str


@strawberry.type
class OperatorOrderLineType:
    product_key: str
    quantity: float
    unit_of_measure: str
    line_id: str
    kind: str
    unit_price: MoneyType | None
    line_total: MoneyType | None
    shipped_quantity: float
    delivered_quantity: float
    invoiced_quantity: float
    scheduled_date: str | None


@strawberry.type
class OperatorTimelineEntryType:
    status: str
    occurred_at: str


@strawberry.type
class OperatorPartiesType:
    end_customer_name: str
    ship_to: str
    subsidiary_id: str
    quote_id: str


@strawberry.type
class OperatorOrder:
    order_id: str
    tenant_id: str
    client_reference: str
    status: str
    owning_connection_id: str | None
    erp_order_id: str | None
    lines: list[OperatorOrderLineType]
    timeline: list[OperatorTimelineEntryType]
    subtotal: MoneyType | None
    fulfillment_status: str  # UNFULFILLED | PARTIALLY_FULFILLED | FULFILLED (ADR-0014)
    delivery_status: str  # NOT_DELIVERED | PARTIALLY_DELIVERED | DELIVERED (FR-D3)
    invoice_status: str  # NOT_INVOICED | PARTIALLY_INVOICED | INVOICED
    parties: OperatorPartiesType


@strawberry.type
class ConnectionType:
    connection_id: str
    erp_type: str
    instance_label: str
    base_url: str
    credentials: strawberry.scalars.JSON  # generic non-secret params — never the secret itself
    status: str
    secret_ref: str
    has_webhook_secret: bool
    # Derived from the adapter registry at read time (ADR-0021), never stored — whether
    # this erp_type has working delivery code, not just a connection row.
    has_adapter: bool
    # ADR-0022: what `hasAdapter` alone can't say — whether this erp_type's mapping is
    # NEEDS_MAPPING (genuinely actionable on the Mapping page), MAPPING_IN_PROGRESS,
    # AWAITING_ADAPTER (already approved, waiting for the generated code to land), or
    # ADAPTER_READY (same fact as `hasAdapter`, spelled out for display).
    mapping_status: str


@strawberry.type
class BindingType:
    binding_id: str
    tenant_id: str
    connection_id: str
    erp_customer_id: str
    status: str


@strawberry.type
class ResellerType:
    tenant_id: str
    name: str


@strawberry.type
class SubsidiaryType:
    subsidiary_id: str
    name: str
    country: str
    language: str


@strawberry.type
class QuoteLineType:
    product_key: str
    name: str
    kind: str
    unit_price: MoneyType
    unit_of_measure: str
    tax_code: str | None
    tax_rate: float | None
    line_discount: MoneyType | None


@strawberry.type
class QuoteType:
    quote_id: str
    tenant_id: str
    subsidiary_id: str
    end_customer_name: str
    ship_to: str
    currency: str
    valid_from: str
    valid_until: str
    routed_to_connection_id: str
    status: str
    lines: list[QuoteLineType]


@strawberry.input
class QuoteLineInput:
    product_key: str
    name: str
    unit_price: float
    kind: str = "PHYSICAL"
    unit_of_measure: str = ""
    tax_code: str | None = None
    tax_rate: float | None = None
    tax_inclusive: bool = False
    line_discount: float | None = None


@strawberry.type
class OrderEventType:
    """The raw event stream for one order — the developer/event-sourcing view. Not a
    projection: this is exactly what's in the `events` table, in order."""

    event_type: str
    version: int
    occurred_at: str
    correlation_id: str | None
    payload: strawberry.scalars.JSON


# --- ERP field-mapping proposer (operator "ERP mapping" tab) ---
@strawberry.type
class CanonicalSchemaType:
    name: str
    field_count: int


@strawberry.type
class MappingEntryType:
    erp_field: str
    canonical_field: str
    sample_data: str
    confidence: int  # 0-100; treat below ~95 as something to check by hand


@strawberry.type
class MappingJobType:
    job_id: str
    erp_name: str
    status: str  # PENDING | PROCESSING | DONE | FAILED
    mapping: list[MappingEntryType]  # empty until status is DONE (or if nothing matched)
    error: str | None
    adapter_run_id: str | None  # set once the mapping has been approved & handed off
    created_at: str
    schema_name: str | None  # null when the canonical fields were pasted for this job only
    sample_files: list[str]  # filenames of the ERP exports attached to this job


@strawberry.type
class AdapterRunType:
    """A snapshot of the `erp-agent-service` run that implements an approved mapping."""

    status: str  # PENDING | PROCESSING | DONE | FAILED
    branch: str | None
    pr_url: str | None
    error: str | None


@strawberry.input
class SampleFileInput:
    """One uploaded ERP sample export — the file read client-side into `content`. The
    backend truncates it to a sample before storing (no raw file is kept)."""

    filename: str
    content: str


# --- ERP onboarding probe (fetch samples live instead of a manual file upload) ---
@strawberry.input
class AuthConfigInput:
    """How to authenticate the probe's calls to the new ERP. `auth_type` is one of
    `AuthType`'s values (NONE | API_KEY_HEADER | BASIC | BEARER_TOKEN) — declarative auth
    only; anything needing a handshake or a redirect UI isn't supported here yet, use the
    manual sample-file upload (`submitMapping`) instead. `secret` is write-only: it goes
    straight into Secrets Manager and is never echoed back."""

    auth_type: str
    params: strawberry.scalars.JSON
    secret: str | None = None


@strawberry.input
class SampleRequestInput:
    """One HTTP call the probe makes to pull a sample of one kind of record (e.g.
    "orders"). `path` is appended to `baseUrl`."""

    label: str
    method: str = "GET"
    path: str = ""
    query_params: strawberry.scalars.JSON = strawberry.field(default_factory=dict)


@strawberry.type
class ProbeSampleType:
    """One `SampleRequestInput`'s outcome. Exactly one of `text`/`error` is set."""

    label: str
    text: str | None
    error: str | None


@strawberry.type
class SuggestedRequestType:
    """One LLM-suggested `SampleRequestInput` — a starting point the operator reviews
    and can edit before firing anything (`probeErpSamples`/`submitMappingFromProbe`)."""

    label: str
    method: str
    path: str
