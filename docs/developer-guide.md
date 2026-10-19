# Developer guide — the data flow, traced end to end

One quotation, followed from the ERP into AdminOps and back out to the reseller. Payloads, events, and status conversion are the real ones. If you only read one doc to see how this system behaves at runtime, read this one.

The business version of the same story is [business-case.md](business-case.md). New to event sourcing? Read [event-sourcing-explained.md](event-sourcing-explained.md) first. Every table is in [database-schema.md](database-schema.md).

---

## 0. The shape of the system in one minute

Two processes run the same code (`src/composition.py` wires both):

- **api** (`src/api/app.py`) — GraphQL for the reseller and the operator, plus the inbound ERP webhook. It writes events and reads projections. It does no ERP I/O.
- **worker** (`src/worker/main.py`) — the outbox relay, the queue consumers, and the reconciliation scheduler. Talking to the ERP happens here.

`Order`, `Shipment`, and `Invoice` are event-sourced. Connections, bindings, subsidiaries, and webhook endpoints are ordinary rows.

The live entry does not start from a GraphQL `placeOrder`. The worker polls each active connection, adopts a sales order that already exists, and later polls status, deliveries, and invoices. `placeOrder`, `OrderSubmitted`, and `submit` are still in the tree. Nothing on this path calls them.

```
scheduler ─▶ each ACTIVE connection
               ├─ for each VERIFIED binding: fetch_partner_orders
               │     company matches subsidiary, customer matches reseller
               │     Order.observe ─▶ OrderObserved ─▶ events + outbox
               └─ for each adopted order: fetch_status, fetch_shipments, fetch_invoices

outbox ─▶ relay ─▶ Service Bus topic
                     ├─ projections        build the orders read model
                     ├─ webhook-dispatch   POST to the reseller (not on OrderObserved)
                     └─ order-fulfillment  shipment/invoice scores back onto the order
```

---

## 1. Setup data, before any quotation

An operator writes these rows. None of them are event-sourced. IDs below are reused in the walkthrough.

| Table | Example | What it decides |
|---|---|---|
| `erp_connections` | `conn_odoo_in` — `erp_type=ODOO`, `base_url`, `credentials={"database","username"}`, `secret_ref`, `status=ACTIVE` | Which database we log into |
| `subsidiaries` | `sub_in` — name, country, language | The distributor company |
| `subsidiary_routes` | `sub_in` → `conn_odoo_in`, `erp_company_id=1` | That database is this subsidiary. One connection belongs to one subsidiary |
| `tenant_connection_bindings` | `tnt_acme` + `conn_odoo_in` + `erp_customer_id=42`, `status=VERIFIED` | Inside that database, Acme is customer 42 |

Secrets are pointers (`secret_ref`), resolved from Key Vault at call time. The webhook secret is a different secret from the login.

A quotation is adopted only when both matches succeed: `sale.order.company_id` equals `erp_company_id`, and `partner_id` equals a verified `erp_customer_id`. Otherwise the row stays in Odoo.

---

## 2. Direction 1 — Odoo quotation → adopted order

### 2.1 The poll

`ReconcileSweeper` calls `discover` for each active connection (`composition.py`). Discover resolves the connection, and for each verified binding calls `OdooAdapter.fetch_partner_orders`.

Odoo reads `sale.order` where `partner_id` is the binding's customer id, then the product lines. The adapter returns an `ErpPartnerOrder`:

| Odoo | Canonical | Example |
|---|---|---|
| `sale.order.name` | `erp_order_id` | `S00042` |
| `client_order_ref`, or the name if blank | `client_reference` | `PO-2024-1182` |
| `company_id` | `erp_company_id` | `1` |
| `product.product.default_code` | `product_key` | `ANVIL-100` |
| `product_uom_qty` | `quantity` | `2` |
| `price_unit` + order currency | `unit_price` | `19.99 USD` |

A line with no Internal Reference, or a quantity of zero, is dropped. If every line is dropped, the order is not adopted. Section and note lines are ignored.

Discover then looks up the subsidiary with `QuoteService.find_subsidiary(connection_id, erp_company_id)`. No match, no adopt.

### 2.2 Event: `OrderObserved` → state `SENT_TO_ERP`

`OrderService.observe_erp_order` emits one event. The id is `ord_{connection_id}_{erp_order_id}`, so the next poll finds the same aggregate and does not emit again.

```json
{
  "order_id": "ord_conn_odoo_in_S00042",
  "tenant_id": "tnt_acme",
  "client_reference": "PO-2024-1182",
  "lines": [{ "line_id": "ord_conn_odoo_in_S00042_1", "product_key": "ANVIL-100",
              "quantity": "2", "unit_of_measure": "",
              "unit_price": {"amount": "19.99", "currency": "USD"} }],
  "product_keys": ["ANVIL-100"],
  "routed_to_connection_id": "conn_odoo_in",
  "erp_order_id": "S00042",
  "subsidiary_id": "sub_in"
}
```

`OrderObserved` is not in `DISPATCHABLE_EVENT_TYPES`. Saving the quotation does not POST to the reseller. The projector records the order at `SENT_TO_ERP` and the locator `(connection, erp_order_id) → order_id`.

`draft` and `sent` do not move status after that. The order sits at `SENT_TO_ERP` until Odoo confirms it.

---

## 3. The fulfillment saga — shipment and invoice (ADR-0018)

The same sweep, after the order is known, calls `fetch_shipments` and `fetch_invoices`.

Odoo shipments are done `stock.picking`s. The picking id is stable across polls. The picking name is the proof of delivery. Odoo invoices are posted `account.move` rows of type `out_invoice`. Credit notes are skipped. A SKU that is not on the order is skipped.

`ShipmentService.record_once` saves a `Shipment` aggregate and nothing else. A later poll of the same picking does not append another event.

```json
{ "shipment_id": "shp_7", "order_id": "ord_conn_odoo_in_S00042",
  "lines": [{"line_id": "ord_conn_odoo_in_S00042_1", "quantity": "2"}],
  "proof_of_delivery": "WH/OUT/00042" }
```

`InvoiceService.record_once` does the same for `InvoiceRecorded`. The order is not loaded in that call.

`ShipmentRecorded` / `InvoiceRecorded` are filtered to `order-fulfillment`. `OrderFulfillmentConsumer` loads the order and applies:

| Event consumed | Order command | Event emitted |
|---|---|---|
| `ShipmentRecorded` | `record_fulfillment` | `OrderLineFulfilled` — adds shipped quantity, and derives delivered |
| `InvoiceRecorded` | `record_invoice` | `OrderLineInvoiced` — adds invoiced quantity |

The order must already be `CONFIRMED` or `CLOSED`. Recording against `SENT_TO_ERP` raises, the message retries, and a permanent failure dead-letters. Confirm the order in Odoo before the delivery is recorded, or the shipment waits.

A box is delivered when a carrier or a proof of delivery is present. Odoo supplies the picking name as that proof. A license is delivered when it ships.

The lifecycle `state` does not change when a score moves (ADR-0014). Given a line ordered `2`:

| Recorded so far | Fulfillment | Delivery | Invoice |
|---|---|---|---|
| nothing | UNFULFILLED | NOT_DELIVERED | NOT_INVOICED |
| shipment qty 1 | PARTIALLY_FULFILLED | PARTIALLY_DELIVERED | NOT_INVOICED |
| shipment qty 2 | FULFILLED | DELIVERED | NOT_INVOICED |
| invoice qty 2 | FULFILLED | DELIVERED | INVOICED |

Between the shipment row and the score update there is one queue hop. Redelivery is safe because of `processed_events`.

---

## 4. Direction 2 — Odoo status → reseller notification

### 4.1 How status arrives

Two ways, same mapping:

- **Webhook.** `POST /erp/webhook/{connection_id}/{secret}` with `erp_order_id`, `state`, and `invoice_status`. The body is stored in `erp_event_inbox` before it is parsed. The locator finds an order that already exists. A webhook does not adopt a new order.
- **Poll.** `fetch_status` reads `state` and `invoice_status` on `sale.order` by name. This is what moves an order when Odoo never calls us.

### 4.2 Status conversion (`status_mapping.py`)

| Odoo `state` | Odoo `invoice_status` | Canonical | Event | State after |
|---|---|---|---|---|
| `sale` or `done` | not `invoiced` | `CONFIRMED` | `OrderConfirmed` | `CONFIRMED` |
| any | `invoiced` | `CLOSED` | `OrderClosed` | `CLOSED` |
| `cancel` | any | `CANCELLED` | `OrderCancelled` | `CANCELLED` |
| `draft`, `sent`, anything else | | none | | unchanged |

`confirm()` is valid from `SENT_TO_ERP`. `close()` is valid from `CONFIRMED`. Repeating either is a no-op. `StatusApplier` ignores a backward move.

### 4.3 Lifecycle on the live path

```
OrderObserved ──▶ SENT_TO_ERP ──confirm()──▶ CONFIRMED ──close()──▶ CLOSED
                      │
                      └──cancel()──▶ CANCELLED
```

`record_fulfillment` and `record_invoice` are allowed only from `CONFIRMED` or `CLOSED`. They do not change `state`.

`SUBMITTED → VALIDATED → ACCEPTED → send_to_erp`, `OrderRejected`, and `OrderRetrying` belong to `placeOrder` and `DeliveryHandler.submit`. That chain is still in the code. Discover does not enter it. An adopted order is born at `SENT_TO_ERP`.

### 4.4 What the reseller is sent

`webhook-dispatch` handles `DISPATCHABLE_EVENT_TYPES`. `OrderObserved` is not one of them. The body is the same for every event that is: the event name, id, time, and the order id, reseller-facing number, and latest status.

```json
{ "event": "OrderConfirmed", "eventId": "evt_a9f3", "occurredAt": "2026-10-05T09:12:03Z",
  "order": { "id": "ord_conn_odoo_in_S00042", "number": "PO-2024-1182", "status": "CONFIRMED" } }
```

| Event | When the reseller can hear it |
|---|---|
| `OrderConfirmed` | Odoo state is `sale` or `done`, and the order is not fully invoiced |
| `OrderClosed` | Odoo `invoice_status` is `invoiced` |
| `OrderCancelled` | Odoo state is `cancel` |
| `ShipmentRecorded` | A done delivery was recorded |
| `InvoiceRecorded` | A posted customer invoice was recorded |
| `OrderSentToErp`, `OrderRejected`, `OrderRetrying` | The unused submit path. Discover does not emit these |

A row is written to `webhook_deliveries` only when a POST is attempted. AdminOps lists rows whose status is `DELIVERED`, for every reseller. No subscribed endpoint means no row, even though the order is moving.

The POST is signed `t=<timestamp>,v1=<hmac>` over `timestamp + "." + body`.

---

## 5. Event catalog

"Dispatched" means the reseller's endpoint can be POSTed. AdminOps shows the notification only after that POST succeeds.

| Event | Emitted by | Lands in | Dispatched? |
|---|---|---|---|
| `OrderObserved` | `observe_erp_order` on first poll | `SENT_TO_ERP`, subsidiary, locator | No |
| `OrderConfirmed` | status in | `CONFIRMED` | Yes |
| `OrderClosed` | status in | `CLOSED` | Yes |
| `OrderCancelled` | status in, or `cancelOrder` | `CANCELLED` | Yes |
| `ShipmentRecorded` | shipment aggregate, from the poll | saga → `OrderLineFulfilled` | Yes |
| `InvoiceRecorded` | invoice aggregate, from the poll | saga → `OrderLineInvoiced` | Yes |
| `OrderLineFulfilled` | fulfillment consumer | shipped and delivered quantities | No |
| `OrderLineInvoiced` | fulfillment consumer | invoiced quantity | No |
| `OrderSubmitted`, `OrderValidated`, `OrderReadyForDelivery`, `OrderSentToErp`, `OrderRejected`, `OrderRetrying` | `placeOrder` / `DeliveryHandler` | the unused submit chain | only Rejected, SentToErp, Retrying |

---

## 6. Where to go deeper

- The same story without payloads: [business-case.md](business-case.md).
- Tables and columns: [database-schema.md](database-schema.md).
- Why the subsidiary and the binding are separate, and why `OrderObserved` is not a notification: [adr/0019-order-routing.md](adr/0019-order-routing.md).
- Odoo field names and the click-through: [erps/odoo/README.md](erps/odoo/README.md), [erps/odoo/supply-chain-check.md](erps/odoo/supply-chain-check.md).
- A second ERP type: [adding-an-erp.md](adding-an-erp.md). A second Odoo database is another connection, not another adapter.
- Run it: [local-setup.md](local-setup.md).
