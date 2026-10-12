# Canonical field reference

The ERP-neutral field set every adapter maps to/from. There is no schema class or config
table for this — it's defined implicitly by three things staying in agreement: the
`Order`/`OrderLine` domain dataclasses, the dict shape `OrderReaderAdapter.read_payload`
produces, and what each adapter reads back out of that dict
(`docs/adding-an-erp.md`/`docs/erp-integration-patterns.md` call it "the ERP-neutral
payload"). Mapping is deliberately per-adapter code, not a shared declarative engine
(`aidlc-docs/inception/application-design/target-architecture.md` §6) — this doc exists
so that choice doesn't also mean the field list only lives in code.

This is the one place that list is written down. If you add or rename a canonical field,
update it here too — same rule as any other "one name per concept" (see
`docs/adding-an-erp.md` for the adapter checklist that consumes these names).

## Order-level

| Field | Type | Meaning | Source |
|---|---|---|---|
| `order_id` | str | Platform order id; the idempotency key an adapter searches by before creating anything | `src/modules/sales/ordering/application/adapters.py:64` |
| `client_reference` | str | Reseller's own reference — not unique | same |
| `erp_customer_id` | str \| None | Resolved ERP-side customer id, from the tenant/connection binding; operator-only | same |
| `owning_connection_id` | str | Which `ErpConnection` owns this order; operator-only | `docs/database-schema.md:44` |
| `erp_order_id` | str | The ERP's own order id/name, once submitted; operator-only | same |
| `state` / `status` | enum | Order lifecycle state | `src/modules/sales/ordering/domain/aggregate.py` |
| `ship_to` | str | Delivery address key | `adapters.py:64` |
| `parties` | object | `end_customer_name`, `ship_to`, `subsidiary_id`, `quote_id` | `read_models.py:126` |
| `subtotal` | Money (`{amount, currency}`) | Order subtotal | `read_models.py:126` |
| `fulfillment_status` | enum | UNFULFILLED / PARTIALLY_FULFILLED / FULFILLED | `domain/models.py:112` |
| `delivery_status` | enum | NOT_DELIVERED / PARTIALLY_DELIVERED / DELIVERED | same |
| `invoice_status` | enum | NOT_INVOICED / PARTIALLY_INVOICED / INVOICED | same |
| `timeline` | list of `{status, occurred_at}` | Status history | `read_models.py:126` |

## Line-level (`lines[]`)

| Field | Type | Meaning | Source |
|---|---|---|---|
| `line_id` | str | Line identifier within the order | `domain/models.py:32` |
| `product_key` | str | Our product identifier (an adapter looks this up against the ERP's own product id/code) | same |
| `quantity` | Decimal | Ordered quantity | same |
| `unit_of_measure` | str | Unit the quantity is in | same |
| `kind` | "PHYSICAL" \| "LICENSE" | Line type | same |
| `unit_price` | Money \| None | `{amount, currency}` | same |
| `line_discount` | Money \| None | `{amount, currency}` | same |
| `tax_rates` | list of `{code, rate, inclusive}` | Taxes on this line | same |
| `line_total` | Money \| None | Derived, not stored | `projections/read_models.py:47` |
| `shipped_quantity` | Decimal | Derived from `shipped_qty_by_line` | same |
| `delivered_quantity` | Decimal | Derived from `delivered_qty_by_line` | same |
| `invoiced_quantity` | Decimal | Derived from `invoiced_qty_by_line` | same |
| `scheduled_date` | date | Vendor-promised date | same |

## Shipment / invoice facts

**Not separate tables.** Per ADR-0002, fulfillment/invoice/payment/return are plain
per-line accumulators on the `Order` aggregate itself, not their own canonical
entities — this is the opposite of how some ERPs model it (e.g. Odoo's own
`stock.picking`/`account.move`, or an ERP with distinct order/delivery tables). An
adapter for an ERP that *does* split these into separate exports (separate order table +
delivery table, as SAP/Oracle-style ERPs often do) must reconcile them into these same
per-line keys on submit/fetch_status — don't invent a parallel "delivery" or "invoice"
canonical concept to hold them.

| Field | Type | Meaning | Source |
|---|---|---|---|
| `shipped_qty_by_line` | `dict[line_id, Decimal]` | `domain/aggregate.py:68` |
| `delivered_qty_by_line` | `dict[line_id, Decimal]` | `domain/aggregate.py:69` |
| `invoiced_qty_by_line` | `dict[line_id, Decimal]` | `domain/aggregate.py:70` |
| `carrier` | str \| None | From `OrderLineFulfilled` event | `domain/events.py:114` |
| `proof_of_delivery` | str \| None | Same event | same |
| `vendor_date` | date | From `OrderLineVendorDateSet` event | `domain/events.py:142` |

Today these are operator-recorded only — no adapter pulls shipment/invoice facts *from*
the ERP (`docs/erps/odoo.md:116`). A new adapter whose ERP exposes this data (e.g. a
separate delivery/invoice export) is the first to actually fill these from `fetch_status`
— follow the same per-line-key shape, don't add new top-level fields for it.

## Worked example: Odoo's mapping

See `docs/erps/odoo.md`'s outbound/inbound tables for a full worked mapping against a
real adapter — canonical `line.quantity` → Odoo `sale.order.line.product_uom_qty`, etc.
Each new ERP gets its own page there, same headings.
