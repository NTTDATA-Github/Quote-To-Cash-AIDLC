# JSONPlaceholder Demo ERP

Status: **live, real adapter**
(`src/modules/integration/erp/infrastructure/jsonplaceholder_demo_erp_adapter.py`),
registered as `ErpType.JSONPLACEHOLDER_DEMO_ERP`. This page is sourced from the adapter
code — if it ever disagrees with that file or
`src/modules/integration/erp/domain/status_mapping.py`, the code is right and this is
stale.

## What it is, as far as this platform is concerned

JSONPlaceholder (`https://jsonplaceholder.typicode.com`) is a free, public fake REST API
meant for prototyping against — not a real order-management system. It has exactly six
resources: `/posts`, `/comments`, `/albums`, `/photos`, `/todos`, `/users`. None of them
is a sales order, a product catalog, a shipment, or an invoice. This adapter treats
`/posts` as the closest thing to "the sales order" (one post per canonical order) and
`/users` as the closest thing to "the customer." Everything that doesn't map onto one of
those two resources (product catalog, shipments, invoices, a real status field) simply
doesn't exist in this ERP — see **Known gaps** below for what that means in practice.
This is deliberately a small, honest adapter for a fake backend, not a template for how
a real ERP integration should look (that's Odoo's job — see [../odoo/](../odoo/README.md)).

## How a connection is configured

| `ErpConnection` field | What it is for JSONPlaceholder Demo ERP |
|---|---|
| `base_url` | `https://jsonplaceholder.typicode.com` (or a mock/sandbox pointed at the same shape). |
| `credentials` | Unused — this adapter reads nothing out of the generic bag. |
| `secret_ref` | Unused by the public sandbox (see **Authentication**). Resolves to a bearer token if a real backing account for this ERP type ever requires one. |
| `webhook_secret_ref` | Not applicable — see [webhook.md](./webhook.md). |

## Authentication

**Assumption from JSONPlaceholder's public API documentation
(`https://jsonplaceholder.typicode.com/guide/`), to be verified against the real
account:** the public API requires no authentication at all — every call is a plain,
unsigned HTTPS request. The adapter's `_request` helper sends no `Authorization` header
unless `ErpTarget.secret` is non-empty, in which case it sends `Bearer <secret>` (a
forward-compatible default for a hypothetical real backing account behind this ERP type,
not something the public sandbox needs or checks).

## How an order arrives

This adapter does not create a customer (`/users` rows are the ten fixed seed users in
the public sandbox). `submit` places an order **as** the reseller's bound
`erp_customer_id` directly (used as JSONPlaceholder's own `userId` — no name lookup,
no auto-create; a missing/invalid id is a terminal error, same FR-A1 reasoning as Odoo's
`partner_id`). `fetch_partner_orders` reads existing `/posts?userId={id}` rows for that
customer and adopts the ones whose `body` happens to parse as this adapter's own JSON
line shape (`{"client_reference": ..., "lines": [...]}`) — a row that doesn't parse that
way (e.g. the sandbox's own lorem-ipsum seed posts) is skipped, same "no recognizable
product code → skip" reasoning Odoo applies per line.

## Outbound: canonical order → JSONPlaceholder `POST /posts`

| Canonical | JSONPlaceholder field | Notes |
|---|---|---|
| platform `order_id` (idempotency key, FR-A2) | `posts.title` | Searched (`GET /posts?userId={id}`, matched by `title`) **before** create — same reasoning as Odoo's `client_order_ref`. Against the public sandbox itself this never finds a match: `POST /posts` there is a fake echo that is never actually persisted (documented in JSONPlaceholder's own guide), so every submit "creates" a new id — a real backing account may behave differently; the search is still correct code either way. |
| binding `erp_customer_id` (FR-A1) | `posts.userId` | Used **directly** as JSONPlaceholder's own user id, checked against `GET /users/{id}` first. A missing/invalid id is terminal — never a silent new user. |
| `end_customer_name` | `posts.name` | **Human-reviewed mapping, 96% confidence.** `posts` has no such field in JSONPlaceholder's own public schema — this assumes this account's own schema extends it. Omitted (not sent as `""`) because the canonical order payload (`OrderReaderAdapter.read_payload`) does not populate `end_customer_name` today — a gap upstream of this adapter, not in the mapping. |
| `line.product_key` / `quantity` / `unit_of_measure` | JSON text inside `posts.body` | **Known gap:** no product-catalog endpoint exists in JSONPlaceholder's public API to validate a SKU against (unlike Odoo's `default_code` lookup), so lines are serialized opaquely rather than resolved. |
| *(returned)* `erp_order_id` | `posts.id` | Read back after create (or found by `title` match) and stored as our `erp_order_id`. |

## Status mapping

| Native fields | Canonical status |
|---|---|
| *(none — see below)* | *(always no transition)* |

`fetch_status` calls the real, publicly documented `GET /posts/{id}` and returns
`{"status": <whatever that account's post record puts there>}`. `status_mapping.py`'s
`_map_jsonplaceholder_demo_erp` deliberately maps **every** value to "no transition."

**TODO (account-specific, not guessable from public docs):** JSONPlaceholder's own
public schema has no order-status concept whatsoever — there is nothing to read a real
mapping from without a live account or that account's own API docs. Confirm the real
field name (is it even called `status`?) and its actual value vocabulary (how is
"confirmed" spelled? is there a distinct cancelled value, or does cancelling just delete
the post?) against a real account, then fill in `_map_jsonplaceholder_demo_erp` the same
way `_map_odoo` reads `state`/`invoice_status`. Never guess at those values in the
meantime.

## Shipments and invoices

`fetch_shipments` and `fetch_invoices` both always return `[]`. Neither a shipment nor an
invoice document exists anywhere in JSONPlaceholder's public schema — this is the
"return `[]` when that ERP has no such documents" case `docs/adding-an-erp.md` describes,
not an oversight.

## Known gaps

Real limitations of building this against a fake backend, not hidden:

- **No product catalog to validate against.** Unlike Odoo's `default_code` lookup, there
  is no SKU/catalog endpoint in JSONPlaceholder's public API — line `product_key`s are
  carried opaquely inside `posts.body`, never resolved or fail-closed-checked.
- **Idempotency search never actually finds anything against the public sandbox.**
  `POST /posts` there fakes a successful response (`id: 101`, etc.) but never persists it
  server-side (documented in JSONPlaceholder's own guide) — a retried `submit` against
  the real public sandbox always "creates" a new id rather than returning the first one.
  The search-before-create code is correct for a real backing store; it's the public
  sandbox itself that can't prove the behavior out.
- **`cancel`'s `DELETE /posts/{id}` can't distinguish "didn't exist" from "existed and
  is now gone."** JSONPlaceholder's public sandbox fakes a `200 {}` for `DELETE` on any
  id, real or not — unlike Odoo's explicit not-found check before `action_cancel`.
- **No order-status field** — see **Status mapping** above.
- **`fetch_partner_orders` only adopts posts this adapter itself could have written.**
  A real account's own order-creation UI/flow would presumably write `body` in some other
  shape; until that's known, anything not matching this adapter's own JSON shape is
  silently skipped rather than guessed at.
