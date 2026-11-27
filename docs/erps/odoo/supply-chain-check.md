# Supply-chain check — Odoo

Do this once on the local stack. When it passes, one Odoo sales order has been followed from quotation through delivery and invoice, and the raw webhook is in `erp_event_inbox`.

The click-by-click version, with this database’s customer and product filled in: [test-the-flow.md](./test-the-flow.md).

Adapter facts: [README.md](./README.md). Webhook wiring: [webhook.md](./webhook.md).

## Before you start

```bash
bash scripts/local.sh up
```

| | |
|---|---|
| Odoo | http://localhost:8069 — `admin` / `admin` |
| AdminOps | http://localhost:5173 — `demo-operator` / `DemoPass123!` |
| Connection | `conn_odoo_local` |
| Binding | `tnt_acme` → Odoo partner id **`1`** |
| Distributor | `sub_demo` → Odoo company id **`1`**. A quotation for any other company is not adopted. |
| Webhook secret | `odoo-webhook-demo` |

The sweep runs every 30 seconds. An Access Error on Sales Orders means the Odoo process started before the Sales group was granted: `docker compose restart odoo`.

Partner `1` is the contact created with the database, not whichever customer is already on screen. Turn on developer mode (**Settings → Activate the developer mode**) and open **Contacts**. The record whose URL contains `id=1` is the one this binding follows. A quotation for Acme or Gemini stays in Odoo until that partner id is the one on the binding.

## One-time setup in Odoo

1. **Internal Reference.** **Sales → Products → Products**, open a storable product, set **Internal Reference** (for example `DEMO-BOX`), and save. A line without one is skipped, and an order whose lines are all skipped is not adopted.
2. **Inventory**, if the confirmed order has no Delivery button. **Apps → Inventory → Install**. Odoo then creates a delivery when a sales order is confirmed. Install it before the walk, and use a new quotation afterward.
3. **Webhook.** Follow [webhook.md](./webhook.md) once. The Automation Rule runs inside the Odoo container, so its URL is `http://host.docker.internal:8000/...`, not `localhost`.

## Walk the order

1. **Sales → Orders → Quotations → New.**
2. **Customer:** the partner from the step above (id `1`).
3. **Order Lines:** the product whose Internal Reference you set. Save. The number looks like `S00042`.
4. Wait for the next sweep. Sign in as `demo-operator`. **Orders** shows that number at `SENT_TO_ERP`.
5. On the quotation, click **Confirm**.
6. Open the **Delivery** smart button and click **Validate**. If Odoo asks about an immediate transfer, accept it. The picking must be **Done**.
7. Back on the sales order, **Create Invoice → Create and View Invoice → Confirm**. The invoice must be **Posted**, not left as a draft. Credit notes are ignored.

## What arrives as a webhook, and what is polled

| Step | Webhook | Poll (about every 30s) |
|---|---|---|
| Quotation saved | No. A webhook does not adopt an order. | `sale.order` for partner `1` |
| Confirm | Yes, if the Automation Rule posted `state=sale` | `sale.order` `state` |
| Delivery validated | No. Pickings are not in the webhook body. | done `stock.picking` |
| Invoice posted | Only the status. `invoice_status=invoiced` closes the order. The invoice lines come from the poll. | posted `account.move` (`out_invoice`) |

`draft` and `sent` are stored in the inbox when the POST arrives, and they do not change the order.

## Where to look

**Raw webhook.** After Confirm, this should show the JSON the rule posted, unchanged:

```sql
SELECT received_at, convert_from(body, 'UTF8')
FROM erp_event_inbox
WHERE connection_id = 'conn_odoo_local'
ORDER BY received_at DESC
LIMIT 5;
```

If the inbox stays empty, the rule did not reach the API. Odoo 17 often refuses `import requests` inside an Automation Rule. The poll still moves the order. To prove the inbox itself, post from the host (this `localhost` is correct here):

```bash
curl -i -X POST "http://127.0.0.1:8000/erp/webhook/conn_odoo_local/odoo-webhook-demo" \
  -H "Content-Type: application/json" \
  -d '{"erp_order_id":"S00042","state":"sale","invoice_status":"no","event_id":"manual-1"}'
```

Use the real quotation number. `200` and a new inbox row means the secret and the table are fine. `401` means the secret did not match. `202` means the secret was fine and no adopted order has that number yet.

**AdminOps.** `demo-operator` → **Orders** → the row. Status goes `SENT_TO_ERP`, then `CONFIRMED`, then `CLOSED` once the invoice is posted. Delivered and invoiced quantities are on that order.

**Notifications.** Same sign-in → **Notifications**. A row appears only when a webhook was delivered to an endpoint for a reseller. Saving the quotation does not create one. Confirm, delivery, and invoice can. With no endpoint, this page stays empty even though the order is moving. The row names the reseller.

## Done when

- `erp_event_inbox` has the raw body for this `S00…` number.
- The operator order is `CLOSED`, with a delivered quantity and an invoiced quantity.
- Waiting another 30 seconds does not increase those quantities.
