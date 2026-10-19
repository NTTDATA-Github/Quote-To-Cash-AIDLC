# High-Level Design — AdminOps

C4 **container-level** view. Diagram source: [`hld.drawio`](hld.drawio) (open in
diagrams.net or the VS Code Draw.io extension). It has **three pages**: *(1) Container
view*, *(2) Onboarding and ERP routing*, and *(3) Infrastructure / Deployment (Azure)* —
the Terraform-provisioned topology: VNet, Container Apps environment, Postgres Flexible
Server, Odoo's own Container App + its own Postgres Flexible Server, Azure Container
Registry, Storage + Front Door for the UI, and the one-time Entra OIDC bootstrap. Page 3
is deployment detail deliberately left out of page 1; for the decisions and known gaps
behind it (public access, identity scope, image rebuild rules), see
[ADR-0023](../adr/0023-azure-migration.md) and
[`docs/deploy-azure.md`](../deploy-azure.md) rather than duplicating them here. The
known-gaps table below is for the application architecture (pages 1–2).

Scope: major components, their responsibilities, external dependencies, data stores,
communication paths, and the significant flows and boundaries. It deliberately omits
classes, methods, tables/columns, API schemas, and low-level config. Anything not
established by the product is marked **TBD** rather than assumed.

## System context

**AdminOps** is the distributor's application. Sales writes the quotation in the ERP
(Odoo today). The worker reads that sales order, then confirmation, delivery, and
invoice, and AdminOps shows every order and every notification sent to a reseller.
There is no reseller screen. The reseller receives the webhook on their own system.

Interacting parties and systems:
- **Distributor** (human) — via AdminOps.
- **Reseller** — not a user of this app. Their system receives signed webhooks.
- **ERP (Odoo)** — external system of record. Another Odoo database is another
  connection. A different ERP product needs an adapter (only Odoo is registered today).
- **Reseller webhook endpoints** — external receivers AdminOps's worker posts status to.
- **Keycloak** (identity) and **Azure Key Vault** (credentials) — managed deps.

## Container / component overview

| Component | Purpose / responsibility | Key dependencies |
|---|---|---|
| **AdminOps (SPA)** | The only browser app. Lists every order, every reseller notification, connections, subsidiaries, bindings, and failed messages. | API host (GraphQL /operator); Keycloak |
| **API host** *(Python/FastAPI — the only HTTP server)* | Synchronous interface: GraphQL for AdminOps, the inbound ERP-webhook HTTP route, request authentication/authorization, and reads/writes via the domain. A reseller GraphQL schema remains for machines; it is not a screen. | Domain modules; PostgreSQL; Keycloak; Azure Key Vault |
| **Worker host** *(Python process — not HTTP, not FastAPI)* | Asynchronous processing: order routing, ERP delivery, read-model projection, outbound webhook dispatch, outbox relay, and the reconciliation scheduler (polling fallback). Same codebase/composition root as the API, different entrypoint. | Message bus; Domain modules; PostgreSQL; ERP; Azure Key Vault; Azure AI Foundry |
| **Domain modules** (shared) | The business logic shared by API + Worker, grouped by subdomain (ADR-0017): **`sales/`** (`ordering` — the event-sourced core — plus `quoting`, `shipment`, `invoicing`), **`reference/`** (`catalog`, `connections`, `tenancy`), **`integration/`** (`erp` adapters + registry, inbound/outbound `webhooks`). | PostgreSQL (via hosts) |
| **PostgreSQL (Azure Postgres Flexible Server)** | Single datastore: event store + outbox + snapshots, order projections (read models), and reference/CRUD data. | — (owned by the domain) |
| **Message bus** | Async transport: Azure Service Bus topic → per-consumer subscriptions (+ DLQ). floci locally, Azure Service Bus in prod. | — |
| **Keycloak** | Identity provider (JWT); header-stub provider for local dev. | — |
| **Azure Key Vault** | Stores ERP login and webhook signing secrets (never persisted in the DB). | — |
| **Azure AI Foundry** | gpt-4o deployment used only by the mapping proposer to draft an ERP field mapping; never in the order-sync path. | — |
| **ERP — Odoo** (external) | System of record. Sales writes the quotation here. The worker reads it, then deliveries and invoices. | — |
| **Reseller webhook endpoints** (external) | Reseller-operated receivers for signed status notifications. | — |

## Key flows

1. **Read the ERP sales order** *(scheduled)*
   For each active connection and verified binding, the worker reads `sale.order` for
   that customer. The quotation's company id must match the subsidiary registered on
   that connection. A match appends `OrderObserved` and an outbox row in one
   transaction. AdminOps lists the projected order.

2. **Confirm, deliver, invoice → reseller** *(async)*
   The same poll, or an authenticated inbound webhook, applies status, done deliveries,
   and posted customer invoices. Projections update the AdminOps order.
   `webhook-dispatch` posts a signed notification to the reseller's endpoint. AdminOps
   lists every delivery, including which reseller it went to.

3. **Distributor administration** *(sync)*
   AdminOps → API `/operator` → register connections, subsidiaries (one connection, one
   company id), and reseller bindings. The distributor signs in as the operator role.

4. **Authentication** *(sync)*
   AdminOps obtains a JWT from Keycloak. The operator schema requires the operator role
   and returns every reseller's orders and notifications.

## Data ownership

- **The domain (via API + Worker) owns PostgreSQL** — the single store holding the Order
  event stream + outbox + snapshots, the order read models (projections), and reference
  data (catalog items, ERP connections, reseller bindings, quotes, subsidiaries,
  webhook endpoints/deliveries). The **transactional** aggregates are event-sourced —
  `Order` plus the fulfillment family (`Shipment`/`Invoice`), all on the
  one shared `events`/`outbox`/`snapshots` store, keyed by `aggregate_type` + `stream_id`
  (ADR-0014); reference/config data is plain CRUD.
- **API** publishes order events (writes events + outbox); **Worker** consumes events and
  owns projection writes. **ERP (Odoo)** owns the authoritative order record on its side;
  AdminOps mirrors status back via projections. Secrets are owned by **Azure Key
  Vault**, identities by **Keycloak**.

### Module → table ownership (see diagram page 2)

Modules are grouped by subdomain (ADR-0017): `sales/`, `reference/`, `integration/`.

| Group | Module | Owns (writes) | Reads |
|---|---|---|---|
| — | shared event-sourcing kernel | `events`, `outbox`, `snapshots` | — |
| `sales` | `ordering` *(event-sourced)* | `orders`, `order_status_history` (projections) | persists Order events via the kernel |
| `sales` | `shipment` *(event-sourced)* | — | persists Shipment events via the kernel; `ShipmentRecorded` drives the `orders` fulfilled-quantity score asynchronously via the `order-fulfillment` saga consumer (ADR-0018) |
| `sales` | `invoicing` *(event-sourced)* | — | persists Invoice events via the kernel; `InvoiceRecorded` drives the `orders` invoiced-quantity score asynchronously via the `order-fulfillment` saga consumer (ADR-0018) |
| `sales` | `quoting` | `quotes`, `subsidiaries` | — |
| `reference` | `catalog` | `items` | — |
| `reference` | `tenancy` | `tenant_connection_bindings` | — |
| `reference` | `connections` | `erp_connections` | — |
| `integration` | `erp` (ERP adapters) | — | `erp_connections`, order payload from `orders` |
| `integration` | `webhooks_inbound` | `processed_events` (dedupe) | `orders` (reverse-routing locator) |
| `integration` | `webhooks_outbound` | `webhook_endpoints`, `webhook_deliveries` | — |

`processed_events` is also used by the Worker consumers to dedupe on `event_id`.

## Boundaries

- **Browser (untrusted) vs. trusted server zone** — AdminOps runs in the browser; all
  authority lives server-side (API/Worker/DB). Every request is authenticated and
  role-scoped.
- **Reseller machine vs. AdminOps** — the reseller GraphQL schema hides ERP identity
  (FR-19). AdminOps is the distributor view and shows it, including which reseller a
  notification was sent to.
- **Product boundary** — AdminOps, API, Worker, and domain.
- **Cloud (Azure) boundary** — Keycloak, Key Vault, Service Bus, Postgres Flexible
  Server, and the Container Apps runtimes are Azure-managed.
- **External boundary** — the ERP and reseller webhook endpoints are third-party controlled.

## Deployment / runtime boundaries

- **API host** and **Worker host** are separate deployables (Azure Container Apps in
  the target architecture) so the synchronous and asynchronous workloads scale
  independently; the Worker is further role-splittable (routing / delivery / projections /
  dispatch / relay / reconcile).
- **Local/dev** runs the same code with an in-memory bus and (optionally) floci standing
  in for Azure; **prod** uses the Azure services above.

## Known gaps (honest review, 2026-10-04)

Verified directly against the current code, not carried forward from an earlier pass.
The diagram no longer carries a separate gaps page. The table below is the list.

| # | Gap | Status |
|---|---|---|
| 1 | Reconciliation reads done `stock.picking`s and posted customer `account.move`s. A credit note (`out_refund`) is not applied back onto the invoiced quantity. | Open (credit notes) |
| 2 | `ShipmentRecorded`/`InvoiceRecorded` were excluded from the reseller webhook's dispatchable set, and `OrderFulfilled` (dead since Increment 5) was still on it. | **Fixed** — both added (with `tenant_id` now stamped on `Shipment`/`Invoice`), dead entry removed. |
| 3 | `orders.client_reference` (the reseller's own PO number) had no `UNIQUE` constraint, per-tenant or otherwise. | **Fixed** — app-level check in `OrderService.place_order` (`DuplicateOrderReference`) plus a DB-level `UNIQUE(tenant_id, client_reference)` backstop (migration 0009) for the race window; verified against live Postgres. |
| 4 | `MoneyType.amount` is `float` on both GraphQL schemas, even though the internal `Money`/`TaxRate` value objects are Decimal-exact. | **Fixed** — `amount` is now `String!` on both schemas (verified via printed SDL); UI `Money` type + `formatMoney` updated to parse it for display only, never arithmetic. |
| 5 | The ordering party is still named `tenant`/`TenantId` throughout — there's no multi-tenant SaaS concept here, a "tenant" is a reseller. Misleading to a reader cold on the history, not a functional bug. | Open |

## Non-functional considerations (architecturally significant)

- **Security** — JWT auth (Keycloak) + per-request tenant/role scoping; secrets only in
  Azure Key Vault (never the DB); inbound webhooks authenticated (shared-secret/HMAC);
  outbound webhooks HMAC-signed; FR-19 reseller/ERP data isolation; RLS available in the
  DB for defense in depth.
- **Reliability / consistency** — each aggregate's events + outbox rows are written in one
  DB transaction (no dual-write); at-least-once delivery with per-consumer dedupe; DLQ for
  poison messages; ERP submit is idempotent (keyed on the platform order id); reconciliation
  sweeper as the missed-event safety net. Cross-aggregate links (shipment/invoice → order
  score) are **event-driven sagas** (ADR-0018), eventually consistent — not a shared
  transaction — which is what keeps the modules independently extractable.
- **Scalability** — stateless API/Worker scale horizontally; async work absorbs ERP
  latency/outages via the queue; single Postgres today (read-model/replica scaling: TBD).
- **Observability** — structured logging across API/Worker; delivery log + failed-message
  views in AdminOps. Metrics/tracing stack: **TBD**.
- **Availability / DR** — managed Azure services (Postgres Flexible Server, Service Bus,
  Keycloak on Container Apps). Multi-region topology, RPO/RTO targets, and backup/restore
  policy: **TBD**.
- **Performance** — reads served from projections (CQRS) rather than replaying events;
  specific latency/throughput targets: **TBD**.
