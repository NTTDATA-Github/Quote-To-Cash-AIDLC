# JSONPlaceholder Demo

Status: **live, real adapter** (`src/modules/integration/erp/infrastructure/jsonplaceholder_demo_adapter.py`).
This page is sourced from the adapter code — if it ever disagrees with that file or
`src/modules/integration/erp/domain/status_mapping.py`, the code is right and this is stale.

Single-page exception to this folder's usual three-file shape (see `README.md` here) —
JSONPlaceholder is not a real ERP account: there is no login, no webhook capability, and
no real sandbox order to click through, so `webhook.md`/`supply-chain-check.md` would be
empty shells. This page keeps the same headings `_template/README.md` uses instead.

## What it is, as far as this platform is concerned

[JSONPlaceholder](https://jsonplaceholder.typicode.com) is a free, public fake REST API
("a free online REST API that you can use whenever you need some fake data" — its own
[guide](https://jsonplaceholder.typicode.com/guide/)). It is **not** a real ERP: it has
no concept of a sales order, a customer, a product line, a shipment, or an invoice. This
adapter exists to exercise this platform's own registration/delivery/reconciliation
pipeline end to end against a real, reachable, public HTTP API — not to represent a real
ERP integration.

"The sales order" is stood in with a `/todos` record (fields: `userId`, `id`, `title`,
`completed`, per the public guide). `/todos` was chosen over `/posts` (fields: `userId`,
`id`, `title`, `body`) because `completed` is the one boolean, status-like field
JSONPlaceholder's public schema exposes anywhere — see "Status mapping" below.

## How a connection is configured

| `ErpConnection` field | What it is for JSONPlaceholder Demo |
|---|---|
| `base_url` | e.g. `https://jsonplaceholder.typicode.com` — no trailing `/todos`, the adapter appends it. |
| `credentials` | Unused — this adapter reads no keys from it. |
| `secret_ref` | Unused. ASSUMPTION (JSONPlaceholder public docs): the API is free to use with no signup/API key/auth of any kind, so no credential is ever sent. Point this at any placeholder secret. |
| `webhook_secret_ref` | Not set up — JSONPlaceholder can't call us back (no webhook/automation feature at all). Reconciliation polling (`fetch_status`) is this ERP's only path to a status change, same as any ERP with `webhook_secret_ref` left `None`. |

## Authentication

None. ASSUMPTION (JSONPlaceholder public docs, verified from its guide): every endpoint
is open, no header or token is required or checked. `target.secret`/`target.credentials`
are accepted by the `ErpAdapter` port but unused by this adapter.

TODO (account-specific): if this demo is ever pointed at a real account that *does*
require auth, the actual scheme (API key header? OAuth?) is that account's own detail,
learned from its own docs — not guessable from JSONPlaceholder's public ones.

## How an order arrives

This adapter does not read existing orders out of JSONPlaceholder today in practice.
`fetch_partner_orders` calls `GET /todos?userId={partner_id}` (ASSUMPTION, JSONPlaceholder
public docs: every writable resource models ownership via `userId`, used here as the
closest stand-in for "this partner's orders"), but every row it gets back is filtered out
immediately and it always returns `[]`:

TODO (account-specific): this account's own setup is the only place that could define
which field(s) actually carry a line's `product_key`/`quantity`. JSONPlaceholder's public
`/todos` schema has none at all (just `id`/`title`/`completed`/`userId`) — so there is no
line to adopt an order with yet.

## Outbound: canonical order → JSONPlaceholder `/todos`

What `submit` sends, field by field:

| Canonical | JSONPlaceholder field | Notes |
|---|---|---|
| platform `order_id` (the idempotency key, FR-A2) | `title` | ASSUMPTION (JSONPlaceholder public docs): `title` is the one free-text field `/todos` exposes, used the way Odoo's `client_order_ref` is — searched before create. Known gap: JSONPlaceholder's guide documents that writes are faked and never persisted, so this search can never actually find a prior submission in practice; kept anyway so the adapter's shape matches every other ERP's. |
| binding `erp_customer_id` | `userId` | ASSUMPTION (JSONPlaceholder public docs): `userId` is the schema's one ownership field. Fails closed on a missing/invalid id (same FR-A1 reasoning as Odoo's `partner_id`) — never a silent, nameless auto-created customer. |
| `parties.end_customer_name` | `name` | **Human-approved mapping, confidence 95%**: canonical `end_customer_name` → ERP field `name`. Implemented as given. Not part of JSONPlaceholder's documented `/todos` schema — its fake backend simply echoes back any extra key it is sent. |
| *(fixed)* | `completed` | Always `False` on create. |
| *(returned)* `erp_order_id` | `id` | Read back from the create response (JSONPlaceholder's fake backend always answers `201`, in practice). |

### `submit` — step by step

1. **Idempotency**: `GET /todos?title={order_id}`; if a row comes back, return its `id`
   immediately (known no-op against the real public API — see the table above).
2. **Customer**: `userId = int(erp_customer_id)` from the verified binding — used
   directly. Missing/invalid → terminal error.
3. Build the body (`title`, `completed: false`, `name` if `end_customer_name` is set).
4. `POST /todos` with that body; read back `id` → our `erp_order_id`.

## Status mapping

| JSONPlaceholder `completed` | Canonical status |
|---|---|
| `true` | `CLOSED` |
| `false` | `CONFIRMED` |
| *(anything else/missing)* | *(no transition)* |

`fetch_status` does `GET /todos/{erp_order_id}` and reads `completed` — the one
status-like field the public schema has anywhere (verified from the guide).

TODO (account-specific, cannot be known from JSONPlaceholder's public docs): there is no
field mapped to `CANCELLED`. JSONPlaceholder's public API has no concept of cancellation
at all — if the real account this demo eventually points at represents a cancelled order
some other way (a custom field, a title convention, a separate resource), that can only
be learned from that account's own setup/API docs. `cancel` still issues `DELETE
/todos/{erp_order_id}` (ASSUMPTION, JSONPlaceholder public docs: the documented verb for
removing a resource), but per the guide this never actually removes anything server-side
either — a known gap, not a TODO.

## Shipments and invoices

`fetch_shipments` and `fetch_invoices` always return `[]`. Verified from JSONPlaceholder's
public guide (not a TODO): there is no delivery/shipment or invoice/billing resource of
any kind in its schema (`/posts`, `/comments`, `/albums`, `/photos`, `/todos`, `/users` —
none of them).

## Known gaps

Real limitations of building this against a public, non-persisting fake API, not hidden:

- **Nothing written is actually persisted.** JSONPlaceholder's own guide documents that
  `POST`/`PUT`/`PATCH`/`DELETE` are faked — the idempotency search in `submit` and the
  `DELETE` in `cancel` are both real HTTP calls with no real effect to find/undo against
  a backend that never stores what it's sent.
- **No line items at all.** `/todos` has no product/quantity fields, so canonical order
  lines are never sent to JSONPlaceholder, and `fetch_partner_orders` can never adopt a
  "line" from it (see the TODO above).
- **No cancellation signal.** `status_mapping.py`'s `_map_jsonplaceholder_demo` never
  returns `CANCELLED` — see the TODO above.
- **No shipments/invoices.** Both `fetch_shipments`/`fetch_invoices` are permanently `[]`
  — there is no such resource in JSONPlaceholder's public schema.
- **`capabilities` is deliberately empty** (`tax`/`uom`/`multi_currency` don't exist in
  this schema; `fail_closed_product` has nothing to resolve; `idempotency` isn't claimed
  as a real guarantee given the non-persisting backend above).
