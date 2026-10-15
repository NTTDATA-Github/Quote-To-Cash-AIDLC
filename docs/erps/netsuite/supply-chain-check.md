# Supply-chain check — NetSuite

What a developer does to prove one sales order is followed all the way through. Same
headings as every ERP; Odoo is the live-instance copy
([../odoo/supply-chain-check.md](../odoo/supply-chain-check.md)). Until a real NetSuite
sandbox is wired, this walk runs against the **mock** (`scripts/mock_netsuite.py`), which
speaks the same SuiteTalk REST dialect — the adapter cannot tell the difference.

## Before you start

- The stack is up, and the mock NetSuite is running (`scripts/local.sh up` starts it on
  `http://127.0.0.1:8075`, or run `python -m scripts.mock_netsuite --port 8075 ...` with the
  same TBA credentials you put in the connection's secret).
- A NETSUITE `erp_connections` row (`base_url` = the mock, `credentials` =
  `{account_id, consumer_key, token_id}`, `secret_ref` → `{consumer_secret, token_secret}`),
  a verified binding whose `erp_customer_id` is a seeded mock customer (`101`), and a
  subsidiary route if you exercise discovery.
- Where to sign in: AdminOps (`demo-operator`). The "ERP" here is the mock; its state is
  seeded in-process (items `ANVIL`/`SPRING`/`GEAR`, customer `101`).

## One-time setup in the ERP

- The product code the adapter treats as `product_key` is the item `itemid` — the mock
  seeds `ANVIL`, `SPRING`, `GEAR`. Add more via `MockNetSuiteState.items` if needed.
- No webhook (polling-only — see [webhook.md](./webhook.md)).

## Walk the order

The customer on every document must be the binding's customer (`entity = 101`); a document
for anyone else is invisible here. Against the mock, the "warehouse"/"billing" clicks are
`MockNetSuiteState.add_fulfillment(...)` / `add_invoice(...)` /
`set_status(...)` (what `tests/integration/test_netsuite_adapter_against_mock.py` does), or
the real `!transform/itemFulfillment` / `!transform/invoice` REST calls.

1. Place an order in the portal that routes to the NETSUITE connection — the adapter
   `submit`s a `salesOrder` (externalId = the platform order id).
2. It confirms — `fetch_status` reads "Pending Fulfillment" → `CONFIRMED`.
3. Fulfill it — an `itemFulfillment` is created from the order.
4. Invoice it — an `invoice` is created; set status to "Billed".

## What arrives as a webhook, and what is polled

| Step | Webhook | Poll |
|---|---|---|
| Document saved | — | `fetch_partner_orders` |
| Confirmed | — | `fetch_status` |
| Delivered | — | `fetch_shipments` |
| Invoiced | — | `fetch_invoices` |

NetSuite is polling-only; nothing is a webhook. The poll adopts and advances the order.

## Where to look

- Operator order page — status, delivered quantity, invoiced quantity.
- The mock's state (in-process) or its stdout — the created salesOrder/fulfillment/invoice
  internal ids and `tranId`s.
- Reseller notifications — only after a later event was actually delivered to an endpoint.

## Done when

- The operator order shows confirmed, then delivered, then invoiced.
- A second poll (reconcile sweep) does not increase the quantities — the same fulfillment
  and invoice internal ids are recorded once (`shp_<id>` / `inv_<id>`).
