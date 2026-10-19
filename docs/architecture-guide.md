# Architecture guide

How the system is shaped and why. This is the map; the [ADR log](adr/README.md) holds the
individual decisions (what we chose, what we rejected, why) and the
[HLD](architecture/hld.md) holds the C4 container diagram. For runtime behaviour traced step
by step, see the [developer guide](developer-guide.md).

## 1. Context and intent

AdminOps fronts (eventually) several ERPs. Sales writes the order in the ERP; the
distributor reads every order and every reseller notification in AdminOps. One ERP is live (Odoo); the whole
design is organised around making the *next* ERP a small, contained change rather than a
rewrite. The guiding posture: a modular monolith with clean seams, built so modules can be
pulled into their own services when (and only when) there's a reason to.

## 2. Module map

Business logic is a shared library grouped by subdomain (ADR-0017), under `src/modules/`:

| Group | Modules | Responsibility |
|---|---|---|
| **`sales/`** (order lifecycle) | `ordering`, `quoting`, `shipment`, `invoicing` | Everything from quote to order to the shipment and invoice facts recorded against it. `ordering`, `shipment`, and `invoicing` are event-sourced; `quoting` is CRUD. |
| **`reference/`** (master data) | `catalog`, `connections`, `tenancy` | The lookup data orders are routed and priced against. A **leaf**: it imports neither of the other groups. |
| **`integration/`** (edges) | `erp` (adapters + registry + status mapping), `webhooks_inbound`, `webhooks_outbound` | Everything that talks to a system outside ours. |

Two boundaries are **machine-enforced** by `import-linter` (`pyproject.toml`), not just
convention:
- `reference` is a leaf (must not import `sales` or `integration`).
- `sales` must not import `integration` — the shipment/invoice → order link is an
  event-driven saga (ADR-0018), so there is no code dependency to justify an import.
- the domain is framework-free (no `boto3`/`fastapi`/`strawberry` inside `modules` or the
  event-sourcing kernel) and layered (`shared ← modules ← api/worker`).

Per-ERP code will live under `integration/erp/adapters/<erp>/` when a second ERP arrives;
until then the single Odoo adapter sits directly in `integration/erp` (deliberate YAGNI).

## 3. Runtime topology

Same code, two entrypoints (`src/composition.py` is the one place the object graph is wired;
`APP_PROFILE` selects in-memory vs. Postgres infrastructure):

- **api** — FastAPI: reseller + operator GraphQL, the inbound ERP webhook, health. Writes
  events, reads projections. No ERP I/O.
- **worker** — headless: the Service Bus consumers, the outbox relay, the reconciliation scheduler.
  Role-splittable via `WORKER_ROLE` (ADR-0010): `order-processing`, `order-delivery`,
  `order-fulfillment`, `projections`, `webhook-dispatch`, `relay`, `reconcile` — each an
  independently scalable thread, all in one process by default.

Backing services: a single **Postgres** (event store + outbox + snapshots + projections +
reference data, ADR-0004), and an **Azure Service Bus topic → subscriptions** bus. Locally the bus is the
in-memory implementation; in production it's Azure, with api/worker on Azure Container Apps. See the [HLD](architecture/hld.md) for the container diagram
and data-ownership tables, and [local-setup.md](local-setup.md) to run it.

## 4. The consistency model (the heart of it)

Three layers, each a deliberate choice:

1. **Event sourcing for the transactional aggregates** (ADR-0002, amended by ADR-0014).
   `Order` has a real state machine and a history worth replaying (its timeline *is* its
   events); `Shipment` and `Invoice` are event-sourced too, reusing the same kernel.
   Reference/config data — connections, items, bindings,
   quotes, subsidiaries — are plain rows. Event sourcing is applied where it earns
   its keep, not as a house style.
2. **Per-aggregate transactional outbox** (ADR-0007). An aggregate's events and their outbox
   rows commit in **one** transaction — no dual-write, the stream and the outbox can't
   diverge. A relay publishes the outbox; consumers are idempotent (dedupe on `event_id` via
   `processed_events`). At-least-once + monotonic state means duplicate/out-of-order delivery
   is safe.
3. **Cross-aggregate effects are event-driven sagas** (ADR-0018), *not* shared transactions.
   Recording a shipment saves a `Shipment` and publishes `ShipmentRecorded`; a consumer in
   `ordering` reacts and bumps the order's score. This is eventually consistent, and it is
   exactly what lets `sales`' sub-modules be independent. (This superseded an earlier
   cross-aggregate `UnitOfWork`.)

**CQRS**: writes go through events; reads go through projections (`orders`,
`order_status_history`). A projector rebuilds the read models from the event stream, so a
GraphQL read never replays the store.

## 5. Tenancy, routing, identity, security

- **Tenancy / ownership** (ADR-0005/0006): a reseller↔ERP-customer link is a `binding` row,
  not an identity-resolution service. Routing (`resolve_owning_connection`) is driven by
  **which connection owns the items**, verified against the tenant's binding — not by the
  caller. One order → one connection (mixed-ERP orders are refused).
- **Identity** (ADR-0009): one provider (Keycloak) for human and machine-to-machine auth;
  a header stub locally. The API rejects unauthenticated calls before GraphQL executes.
- **Security**: secrets are pointers resolved from Key Vault (never stored raw), with
  the inbound-webhook secret kept distinct from the ERP login secret; reseller surfaces
  never expose ERP identity (FR-19); row-level-security policies exist on the order tables
  for defense in depth (enabling an app DB role is a tracked, not-yet-activated step).

## 6. Messaging topology

Transactional outbox → `platform-domain-events` (Service Bus topic) → Service Bus subscription queues, each with
an `eventType` filter policy and a DLQ (`maxReceiveCount=5`). `MessageGroupId = order_id`
(per-order ordering, cross-order parallelism); `MessageDeduplicationId = event_id`.

| Queue | Receives | Consumer |
|---|---|---|
| `order-processing` | `OrderSubmitted`, `OrderAmended` | validate + ownership routing |
| `order-delivery` | `OrderReadyForDelivery`, `OrderCancellationRequested` | ERP submit/cancel |
| `order-fulfillment` | `ShipmentRecorded`, `InvoiceRecorded` | the fulfillment saga (bumps order scores) |
| `projections` | all events | build read models |
| `webhook-dispatch` | lifecycle events | outbound reseller notifications |

Provisioned by Terraform in `infra/azure/modules/messaging`. Plain-CRUD domain facts (`ItemSynced`, `ConnectionRegistered`, …) publish onto the same
topic via the same outbox with no consumer yet — durably recorded, wired to a queue later
with a filter-policy change, not a producer change.

## 7. Extensibility — adding an ERP

An adapter + registry pattern (ADR-0003), keyed by ERP *type*, not connection — one adapter
instance serves every instance of that ERP (it's stateless; every call takes an `ErpTarget`
resolved per-connection). Onboarding a new ERP type is roughly four touch points: an adapter
implementing the port, a registry entry, a status-mapping function, and (for inbound) a
webhook route choice. Each adapter declares its `ErpCapabilities` (ADR-0015, declared now,
behaviourally gated once a second adapter exists). Full checklist:
[adding-an-erp.md](adding-an-erp.md); cross-ERP patterns (rich vs. thin webhooks, multi
instance/tenant): [erp-integration-patterns.md](erp-integration-patterns.md).

## 8. Key decisions (the ADRs an architect should read first)

| ADR | Decision |
|---|---|
| [0001](adr/0001-modular-monolith.md) | Modular monolith (`api` + `worker`), not microservices |
| [0002](adr/0002-event-source-order-only.md) | Event-source `Order` only; everything else CRUD |
| [0003](adr/0003-erp-adapter-registry.md) | ERPs plug in via adapter + registry |
| [0004](adr/0004-single-shared-postgres.md) | One shared Postgres |
| [0007](adr/0007-async-outbox-reconciliation.md) | Async outbox delivery + polling fallback |
| [0014](adr/0014-orthogonal-fulfillment-invoice-status.md) | Fulfillment/invoice status derived, orthogonal to lifecycle |
| [0016](adr/0016-price-from-quote-not-catalog.md) | Price lives on the quote; an order replies to a quote |
| [0017](adr/0017-module-grouping-and-fulfillment-split.md) | Subdomain grouping; split `fulfillment` into `shipment` and `invoicing` |
| [0018](adr/0018-shipment-invoice-order-saga.md) | Shipment/invoice → order is an event-driven saga |

The full index (all 18) is in [adr/README.md](adr/README.md).

## 9. Deliberately deferred (roadmap, not gaps)

Scoped future work, each additive rather than a rewrite — recorded so they're decisions, not
surprises:

- **A second ERP adapter** — the design's main proof point; nothing is written yet.
- **Credit notes** — posted customer invoices are pulled from the ERP. A refund does not
  reduce the invoiced quantity.
- **Activating row-level security** with a dedicated app DB role (policies exist; the app
  currently connects as the table owner, which is RLS-exempt).
- **`app`/`worker` as docker-compose services** — today they run from the venv alongside the
  compose-managed backing services.
- **Richer domains if a real ERP forces them** — multi-warehouse, lot/serial, kitting/BOM,
  subscriptions, multi-jurisdiction tax, promotional discounts, a standalone Vendor Order
  document.
