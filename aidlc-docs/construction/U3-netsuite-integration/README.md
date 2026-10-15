# U3-netsuite-integration — Functional Design (folded)

Technology-agnostic design for the NetSuite ERP integration. Builds on the integration
module's existing ports (`ErpAdapter`, `ConnectionResolver`, status mapper registry) — no
new abstractions; NetSuite is a new *implementation* behind the existing seams.

## Domain / data mapping

The platform does **not** create NetSuite customers or items; it references them.

| Platform concept | NetSuite record / field |
|---|---|
| Sales order (what we `submit`) | `salesOrder` record (SuiteTalk REST `record/v1`) |
| Idempotency key (platform order id, FR-A2) | `salesOrder.externalId` |
| Customer the order is placed as (FR-A1, from binding) | `salesOrder.entity` = NetSuite customer **internal id** |
| `erp_order_id` returned/stored | NetSuite salesOrder **internal id** (what all later REST calls key on) |
| `product_key` (our SKU) | `item.itemid`; resolved to item internal id via SuiteQL |
| Shipment (`fetch_shipments`) | `itemFulfillment` created from the SO; `tranId` = proof of delivery |
| Invoice (`fetch_invoices`) | `invoice` created from the SO; `tranId` = invoice number |
| Partner orders (`fetch_partner_orders`) | `salesOrder`s for the customer, read via SuiteQL |

## Business rules (mirrors Odoo adapter's two "don't reinvent" rules)

- **Idempotent submit.** Before creating, GET `salesOrder/eid:{order_id}`. If it exists,
  return its internal id — never create a duplicate on a retried submit.
- **Fail closed, no phantom create.** An unresolvable item SKU or a missing/invalid
  `erp_customer_id` is a **terminal** error, never a silently auto-created NetSuite record.
- **Graceful degradation** for tax/UoM naming mismatches (line still submitted), matching
  Odoo's choice — an unknown tax/unit is visible in NetSuite, not a blocked order.

## Authentication (TBA, OAuth 1.0a)

Signature base string = `METHOD & pct(url-no-query) & pct(sorted oauth+query params)`;
signing key = `pct(consumer_secret) & pct(token_secret)`; `Authorization: OAuth realm="<ACCOUNT_ID>", ...`.
Secret is a JSON blob `{consumer_secret, token_secret}` (D-NS-2); non-secret
`account_id`/`consumer_key`/`token_id` from `credentials`. Malformed secret → terminal.

## Error classification (resiliency)

| Condition | terminal? |
|---|---|
| 400/401/403/404, malformed secret, unresolvable item/customer | yes (reject, no retry) |
| timeout, connection error, 429, 5xx | no (retry via SQS redrive) |

## Pure, unit-testable helpers (no live server needed)

- `build_salesorder_lines(order_payload)` — payload → list of resolved line intents.
- `oauth1_authorization_header(method, url, credentials, consumer_secret, token_secret, nonce, timestamp)` — deterministic given nonce+timestamp.
- `parse_record_id_from_location(location_header)` — Location → internal id.
- `_map_netsuite(fields)` — status mapper (never raises; unmapped → None).

## Status mapping — see requirements §6.

## Fit with the rest of the system (unchanged)

`composition.py`, `DeliveryHandler`, `ReconcileSweeper`, webhook ingress do **not** change —
all dispatch on `erp_type: str` through the registry + status-mapper registry. Adding
NETSUITE is purely the four touch points + the dev mock.
