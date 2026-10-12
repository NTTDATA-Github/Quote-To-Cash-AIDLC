# ADR-0019: An order is routed by the connection being read and the binding on it

| | |
|---|---|
| Status | Accepted |
| Affects | `connections`, `tenancy`, `ordering`, `integration`, outbound webhooks |

## In one sentence

A sales order already exists in an ERP. The connection says which instance we are reading, the verified binding says which customer on that instance belongs to which reseller, and every later notification goes to that reseller's endpoints.

## Why this needed a decision

| Problem | Detail |
|---|---|
| People create the quotation in the ERP | This product is a partner application. It does not issue quotes and it does not create purchase orders or sales orders. |
| Several instances, several resellers | The right order has to land on the right reseller, and a later send (not built) has to pick the right instance and the right customer number inside it. |
| A notification is a delivery | A status change with no webhook endpoint is not stored. AdminOps lists every delivery and opens the order. |

## The decision

Two facts, used at different times.

| Fact | Data | What it answers |
|---|---|---|
| Which instance | One `erp_connections` row | Which ERP database we log into |
| Who the reseller is inside that instance | One verified `tenant_connection_bindings` row: `tenant_id` + `connection_id` + `erp_customer_id` | Whose orders to adopt, and which reseller owns them |

The live path uses the second fact to choose the reseller, because the order is already inside a connection the worker is polling. The subsidiary is a third fact on the same document: `company_id` on the quotation. `subsidiary_routes.erp_company_id` says which subsidiary that company is. Adopt stores that subsidiary. A company id that matches no route is not adopted.

`tenant` is the reseller. Login is Cognito `custom:tenant_id` (or the machine scope `o2c/tenant.<id>`). One login, one set of orders, one set of endpoints. Several machines are several webhook endpoints on that same tenant. Several ERPs are several bindings on that same tenant. There is no parent that owns several tenants.

### Where each piece of data comes from, and when it is used

| Data | Where it is written | When it is read | How it is used |
|---|---|---|---|
| `erp_connections` (`erp_type`, `base_url`, `credentials`, `secret_ref`, `status`) | Operator, once per ERP instance. `credentials` is a non-secret bag (Odoo: `database`, `username`). The password is only a Secrets Manager ref. | Every reconcile sweep, for each `ACTIVE` connection. The secret is fetched at resolve time into an `ErpTarget`. | Picks the adapter and logs into that instance. A paused connection is not swept. |
| `webhook_secret_ref` on the connection | Operator, when that instance will call us. Separate from the login secret. | On `POST /erp/webhook/{connection_id}` (HMAC) or `POST /erp/webhook/{connection_id}/{secret}` (shared secret in the path). | Proves the inbound call. Status can also move on the poll if no webhook is configured. |
| `tenant_connection_bindings.erp_customer_id` | Operator. It is the ERP's own customer id (Odoo: integer `res.partner` id). Status must be `VERIFIED`. | At the start of that connection's sweep, once per verified binding. | Passed to `fetch_partner_orders`. Unverified and `REMOVED` bindings are skipped. |
| `tenant_connection_bindings.tenant_id` | Same row, written with the customer id. | At adopt, copied onto the order. After that, every order event carries it. | Outbound dispatch lists endpoints with `list_by_tenant(event.tenant_id)` only. |
| Uniqueness on the binding | Database: `UNIQUE(tenant_id, connection_id)` and `UNIQUE(connection_id, erp_customer_id)`. | At bind time. | One reseller has one customer number per instance. One customer number on one instance cannot belong to two resellers. |
| ERP sales order (`erp_order_id`, `client_reference`, lines) | In the ERP, by the people who sell there. Not written by this product. | Same sweep, default every 900 seconds (`RECONCILE_INTERVAL_SECONDS`; local setup uses 30). | The adapter translates the ERP document into `ErpPartnerOrder`. Odoo reads `sale.order` by `partner_id`, then `sale.order.line`, and uses `product.product.default_code` (Internal Reference) as `product_key`, `product_uom_qty` as quantity, `price_unit` and the order currency as the price. |
| Usable lines | Derived at adopt. | Immediately after the fetch. | A line with an empty product key or a quantity ≤ 0 is skipped. If none remain, the order is not created. |
| Portal order id `ord_{connection_id}_{erp_order_id}` | First successful observe. | Every later poll of the same document. | The second poll finds the aggregate and returns the same id. It does not emit another event. |
| `OrderObserved` | Emitted once, on that first observe. State is `SENT_TO_ERP` with `erp_order_id` set. | By the projector, which records the locator `(connection, erp_order_id) → order_id`. | Not a notification. `OrderObserved` is not in `DISPATCHABLE_EVENT_TYPES`. Noticing a document does not POST anywhere. |
| Later status, shipment, invoice | ERP, then the same sweep (`fetch_status`, `fetch_shipments`, `fetch_invoices`) or an inbound webhook for status. | After the order is known to the locator. | Confirm, close, cancel, reject, retry, `ShipmentRecorded`, and `InvoiceRecorded` are the events that can notify. |
| `erp_event_inbox.body` | Written on every authenticated inbound webhook, before the body is parsed. | Not read by routing. | Raw request bytes for that connection. A failed secret is not a row. The body is not required to be JSON. |
| Webhook endpoint (`url`, `secret_ref`, `event_types`, `is_active`) | The reseller, on their own tenant. The signing secret is shown once and stored as a ref. | When a dispatchable event for that `tenant_id` is published. | Every active endpoint that subscribes to the event type gets one POST. The body is `event`, `eventId`, `occurredAt`, and `order` (`id`, client reference, latest status). |
| `webhook_deliveries` | Written only when a POST is attempted. One row per `(endpoint_id, event_id)`, with `order_id`. | AdminOps lists every row and shows which reseller it was sent to. A click opens that order. | No subscribed active endpoint means the handler returns and stores nothing. |
| Subsidiary and `subsidiary_routes` | Operator. A subsidiary is the distributor's own company. The route row is `subsidiary_id → connection_id` plus `erp_company_id` (Odoo: `res.company` id). | At adopt, matched to `company_id` on the quotation. | The order stores that `subsidiary_id`. One connection belongs to one subsidiary. |

### What a sweep does, in order

1. The scheduler walks active connections. One connection failing (for example a missing secret) does not stop the others.
2. Discover resolves the connection, then for each verified binding calls `fetch_partner_orders(target, erp_customer_id)` and `OrderService.observe_erp_order`.
3. The sweeper polls status, shipments, and invoices for the adopted ids plus any orders already open on that connection.

Inbound webhooks locate an order that already exists (`connection_id` + ERP document id). They do not adopt a new order and they do not look up a customer.

## Alternatives considered

| Option | Rejected because |
|---|---|
| Route by the subsidiary on the way in | The document is already inside one connection. Reading the subsidiary would pick an instance we are not polling. |
| Store every ERP event as a notification, sent or not | A notification is a delivery. An event with no endpoint is not one. |
| One endpoint filter per subsidiary or per connection | One reseller with several machines receives every event for that tenant on every active subscribed endpoint. Splitting by instance is a later filter, not a second tenant. |
| Create the ERP sales order from here (`submit`) | People sell in the ERP. `submit` remains on the adapter and is not called by this path. |

## Consequences

| | |
|---|---|
| ✅ | The right reseller is the binding's `tenant_id`. The right instance is the connection being read. The distributor is the company on the quotation. All three are data. |
| ⚠️ | A quotation whose company id matches no subsidiary is not adopted. |
| ✅ | Odoo field names stay in `odoo_adapter.py`. A second ERP implements the same port calls, including `fetch_partner_orders`. |
| ✅ | A customer number cannot be bound to two resellers on one connection, so two tenants cannot both adopt the same partner's orders. |
| ⚠️ | Orders for a partner who is not on a verified binding are invisible here, even when they are visible in the ERP. |
| ⚠️ | A product line with no Internal Reference (or the other ERP's equivalent code) is skipped. An order whose lines are all skipped is not adopted. |
| ⚠️ | Endpoints are not split by connection or subsidiary. One reseller, several instances, one set of endpoints. |
| ⚠️ | `submit`, the delivery consumer, and `QuoteService.issue_quote` are still in the tree. The live entry does not call them. [ADR-0016](0016-price-from-quote-not-catalog.md) describes the removed quote-then-place loop. |

## Revisit when

A purchase order must be sent from this product again: use the subsidiary route to pick the connection, then the binding to pick `erp_customer_id`, and call `submit`. Or when one reseller must receive one instance's events on one machine and another's on a different machine: add an endpoint filter, do not add a parent company.
