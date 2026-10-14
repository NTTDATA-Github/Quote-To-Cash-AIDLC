# Supply-chain check — JSONPlaceholder Demo ERP

What a developer does, once, to prove one canonical order reaches this ERP and a status
poll can read it back. Same headings as every other ERP's copy of this file; Odoo's
filled-in version (with a real UI to click through) is
[../odoo/supply-chain-check.md](../odoo/supply-chain-check.md). JSONPlaceholder has no
admin UI at all — it's a public API with no login — so "the clicks" below are `curl`
calls instead of button clicks. That's the one real difference from every other ERP's
copy of this file.

## Before you start

- The stack is up (`ERP_ADAPTER_MODE=real` and an `ErpConnection` row with
  `erp_type=JSONPLACEHOLDER_DEMO_ERP` and `base_url=https://jsonplaceholder.typicode.com`,
  or a local mock serving the same shape).
- Which connection row and which binding this walk uses, and which of the ten fixed
  JSONPlaceholder user ids (`1`-`10`) that binding's `erp_customer_id` is.
- Where to see the result: the operator order page (AdminOps, `demo-operator`).

## One-time setup in the ERP

- Nothing to install — JSONPlaceholder is a fixed, read-only public sandbox (`/users`
  always has exactly ids `1`-`10`; `/posts` always has exactly ids `1`-`100` as seed
  data). There is no webhook to wire up — see [webhook.md](./webhook.md).

## Walk the order

1. Place the canonical order through this platform's normal order-submission path, with
   a binding whose `erp_customer_id` is one of `1`-`10`.
2. `submit` calls `GET /users/{id}` (fail-closed customer check), then
   `GET /posts?userId={id}` (idempotency search), then `POST /posts` — confirm with:
   ```bash
   curl -s "https://jsonplaceholder.typicode.com/posts?userId=<erp_customer_id>"
   ```
3. There is no delivery or invoice step for this ERP — `fetch_shipments`/
   `fetch_invoices` always return `[]` (see [README.md](./README.md#shipments-and-invoices)).
4. Poll status: `curl -s https://jsonplaceholder.typicode.com/posts/<erp_order_id>` is
   exactly what `fetch_status` calls. Confirm the operator order page does **not** move
   past its initial state — `status_mapping.py`'s mapper returns no transition for every
   value today (see [README.md](./README.md#status-mapping)).

## What arrives as a webhook, and what is polled

| Step | Webhook | Poll |
|---|---|---|
| Order placed | — (none, see [webhook.md](./webhook.md)) | `fetch_partner_orders` |
| Submitted | — | `fetch_status` (never advances today) |
| Delivered | — | `fetch_shipments` (always `[]`) |
| Invoiced | — | `fetch_invoices` (always `[]`) |

## Where to look

- `erp_event_inbox` — stays empty for this ERP (no webhook route).
- Operator order page — the order reaches "submitted to ERP" with an `erp_order_id`
  (the JSONPlaceholder post id) but no further automatic lifecycle progress, by design
  until the status-mapping TODO is filled in from a real account.
- `curl https://jsonplaceholder.typicode.com/posts/<erp_order_id>` — the live state of
  the post `submit` created (or found) directly from the public API.

## Done when

- `GET /posts?userId=<erp_customer_id>` shows a post with `title == <order_id>`.
- A second submit of the same order returns the same `erp_order_id` found by that search
  (idempotency), not a second post.
- The operator order page shows the order as submitted to this ERP, consistent with
  **Known gaps** in [README.md](./README.md#known-gaps) — not stuck or erroring.
