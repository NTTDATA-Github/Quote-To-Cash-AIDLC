# Supply-chain check — SAP

What a developer does in SAP, once, to prove one sales order is followed all the way
through. Same headings as every other ERP's version of this page; Odoo's filled-in copy
is [../odoo/supply-chain-check.md](../odoo/supply-chain-check.md).

**Not yet run against a live SAP system** — this adapter was built and unit-tested
against SAP's public API documentation with a mocked HTTP seam
(`test_sap_adapter.py`), not a real sandbox. The steps below are what the adapter code
expects to see; they need a real SAP system (and the TODOs in
[README.md](./README.md)'s "Known gaps") filled in before this check can actually be
run and this note removed.

## Before you start

- The stack is up (`bash scripts/local.sh up`) — there is no SAP container in
  `docker-compose.yml` yet (unlike Odoo's), so this needs a real or trial SAP
  system/sandbox reachable from this machine.
- Which connection row has `erp_type: SAP`, its `credentials` (client id, org structure,
  rejection reason code, delivery/billing service URLs — see README.md), and which
  `SoldToParty` number the binding under test uses.
- Where to sign in: the SAP system's own Fiori launchpad, and AdminOps
  (`demo-operator`).

## One-time setup in SAP

- The material number the adapter will treat as `product_key` — must exist in this
  SAP system's material master before a sales order referencing it will create cleanly.
- This account's `sales_order_type`/`sales_organization`/`distribution_channel`/
  `organization_division` and `rejection_reason_code` — TODO: account-specific, fill in
  once known (see README.md's "Known gaps").
- No webhook to set up — see [webhook.md](./webhook.md); the poll does the work.

## Walk the order

Number the clicks. Each step names the customer, the document, and the button.
The customer on the document must be the binding's `SoldToParty`. A document for
anyone else is invisible here.

1. **Create Sales Orders** (Fiori app) → new sales order for the binding's
   `SoldToParty`, with a line for the known material. Save.
2. SAP sales orders are typically already "confirmed" on save (unlike Odoo's separate
   draft → confirm step) — TODO: verify this account's order type doesn't require a
   separate release/approval step before it is poll-visible as confirmed.
3. **Create Outbound Delivery** (Fiori app) for the sales order, then post goods issue.
4. **Create Billing Document** (Fiori app) for the delivery.

## What arrives as a webhook, and what is polled

| Step | Webhook | Poll |
|---|---|---|
| Document saved | — (none wired up; see webhook.md) | `fetch_partner_orders` |
| Confirmed | — | `fetch_status` |
| Delivered (goods issue posted) | — | `fetch_shipments` |
| Invoiced (billing document posted) | — | `fetch_invoices` |

A webhook is not how a new order is adopted even on ERPs that have one — the poll does
that. For SAP today, the poll is the *only* path.

## Where to look

- `erp_event_inbox.body` — not applicable yet for SAP (no webhook route).
- Operator order page — status, delivered quantity, invoiced quantity.
- Reseller notifications — only after a later event was actually delivered to an
  endpoint. Saving the order is not a notification.

## Done when

- The operator order shows confirmed, then delivered, then invoiced.
- A second poll does not increase the quantities.
- This page's "not yet run against a live SAP system" note above has been removed,
  because it just was.
