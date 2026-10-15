# NetSuite Integration — Requirements (Increment: NetSuite ERP + mock)

**Phase**: INCEPTION — Requirements Analysis (adaptive depth: *standard*; Functional Design
folded in, single well-scoped unit — same handling as Increment 2 "Real Odoo Integration").
**Unit**: `U3-netsuite-integration` (mirrors `U3-odoo-integration`; the integration module).
**Status**: Approved by user directive ("Follow AIDLC and build it"); building.

## 1. Intent

Add **NetSuite** as a first-class registered ERP in the platform, implemented against the
real **SuiteTalk REST Web Services** API, and ship a **faithful in-process mock NetSuite**
that speaks the same SuiteTalk REST dialect — so the platform can be developed, tested and
demoed end-to-end today, and switched to a live NetSuite account later with a **config-only**
change (base URL + credentials), no code change. This is the documented four-touch-point
"[adding an ERP](../../../docs/adding-an-erp.md)" change plus the mock.

## 2. In scope

- **FR-NS-1** A real `NetSuiteAdapter` implementing the full `ErpAdapter` port
  (`submit`, `fetch_status`, `fetch_partner_orders`, `fetch_shipments`, `fetch_invoices`,
  `cancel`), stdlib-only HTTP, mirroring `OdooAdapter`'s shape and error discipline.
- **FR-NS-2** NetSuite **Token-Based Authentication** (OAuth 1.0a, HMAC-SHA256) signing of
  every request, per NetSuite's current TBA spec (HMAC-SHA1 support ended 2023.1).
- **FR-NS-3** A `_map_netsuite` canonical-status mapper registered in `STATUS_MAPPERS`.
- **FR-NS-4** `NETSUITE` member on `ErpType`; registry entry in `build_adapter_registry`;
  `erp_netsuite_timeout_seconds` setting.
- **FR-NS-5** A faithful **mock SuiteTalk REST server** (`scripts/mock_netsuite.py`,
  dev-only, stdlib, not shipped in `src/`), covering exactly the endpoints the adapter calls:
  record CRUD for `salesOrder`, external-id lookup (`eid:`), record transform
  (`!transform/itemFulfillment`, `!transform/invoice`), and the SuiteQL query endpoint.
- **FR-NS-6** Idempotent `submit` keyed on the platform order id written as NetSuite
  `externalId` (FR-A2), and **fail-closed** item/customer resolution (no phantom auto-create),
  mirroring the Odoo adapter's two "copy, don't reinvent" rules.
- **FR-NS-7** Docs: `docs/erps/netsuite/{README,webhook,supply-chain-check}.md` from the
  template; `docs/adding-an-erp.md` + root `README.md` updated to reflect two registered ERPs;
  `scripts/local.sh` starts the mock locally.

## 3. Out of scope (explicitly, not silently dropped)

- **Thin-webhook fast path.** NetSuite webhooks are thin (id + "changed"), and the inbound
  webhook service cannot call back into the ERP today
  (see `docs/erp-integration-patterns.md`). A NETSUITE connection therefore runs in
  **polling-only mode** via the reconcile sweeper (already ERP-agnostic, calls
  `fetch_status`/`fetch_shipments`/`fetch_invoices`) — correct eventually, 15-min cadence.
  Wiring the thin-webhook fast path is a separate, documented decision; not built here.
- **Seeding a live NETSUITE connection into demo data.** Documented as a manual step
  (connection row + Secrets Manager JSON secret pointing at the mock); not auto-seeded, to
  avoid changing `seed_demo.py`'s Odoo-focused demo.
- **OAuth 2.0 / RESTlet transport.** TBA (OAuth 1.0a) is the implemented auth; OAuth 2.0 is
  a config/transport swap on the same adapter if needed later.

## 4. Decisions (resolved by the user's directive)

- **D-NS-1 — Mock approach.** Real `NetSuiteAdapter` + a *faithful* standalone SuiteTalk REST
  mock, **not** the generic `StubErpAdapter`. Rationale: "exact mock, no compromise, plug and
  play" — the adapter's real HTTP/OAuth/SuiteQL/transform paths are all exercised against the
  mock, so going live only changes `base_url` + the secret. The generic stub would leave all
  of that unverified and overrides every ERP type globally.
- **D-NS-2 — Secret model.** Pack the two secret TBA components
  (`consumer_secret`, `token_secret`) as a **JSON blob** in the existing single
  `ErpTarget.secret` (resolved from `ErpConnection.secret_ref` via Secrets Manager). The
  non-secret `account_id`, `consumer_key`, `token_id` go in the `credentials` bag. Rationale:
  zero change to the connection/secrets contract (`ErpTarget`, repositories, Secrets Manager
  usage) — truly plug-and-play. The adapter parses the JSON; a malformed/empty secret is a
  **terminal** auth error (do not retry).

## 5. ErpConnection configuration for a NETSUITE connection

| Field | Value for NetSuite |
|---|---|
| `erp_type` | `NETSUITE` |
| `base_url` | Account-specific REST domain, e.g. `https://<ACCOUNT_ID>.suitetalk.api.netsuite.com` (mock: `http://localhost:8075`) |
| `credentials` | `{"account_id": "...", "consumer_key": "...", "token_id": "..."}` (non-secret) |
| `secret_ref` | Secrets Manager ref whose value is `{"consumer_secret": "...", "token_secret": "..."}` |
| `webhook_secret_ref` | Unused for now (polling-only; thin webhooks out of scope) |

## 6. Canonical status mapping (NetSuite sales order → CanonicalStatus)

Reads the sales order's human `status` refName (and `orderStatus` code as fallback), inputs
already lowercased/stripped by `map_native_status`:

| NetSuite status | Canonical |
|---|---|
| `cancelled` / `canceled` (orderStatus terminal) | `CANCELLED` |
| `billed` / `fully billed` / `closed` | `CLOSED` |
| `pending fulfillment` / `partially fulfilled` / `pending billing` / `pending billing/partially fulfilled` | `CONFIRMED` |
| `pending approval` | *(no transition — not yet confirmed)* |

## 7. Resiliency (extension: enabled at adapter-call level, per prior ERP increments)

- RESILIENCY-05/06/10: explicit per-call timeout (`erp_netsuite_timeout_seconds`), and every
  failure classified `terminal` (4xx validation/auth, malformed secret, unresolvable
  item/customer → do not retry) vs non-terminal (timeout, 5xx, connection error → retry via
  SQS redrive). Infra/DR rules (RESILIENCY-02/03/04/08/09/11+) **N/A** — no new infra here.

## 8. Property-based testing (extension: partial, pure functions/round-trips only)

- PBT target: the `_map_netsuite` status mapper (never raises on arbitrary field bags;
  unmapped → `None`) and the pure line-building helper. Request-shaping/idempotency/
  fail-closed are example-based unit tests mocking the HTTP seam (mirrors `test_odoo_adapter.py`),
  plus an end-to-end integration test of the real adapter against the in-process mock.

## 9. Security (extension: baseline not enabled for this local/PoC increment, matching Inc 2)

Nonetheless the existing codebase posture is kept: the secret is resolved via Secrets Manager
and never logged; the TBA signing secret components are never echoed; the adapter logs record
ids/status, never credential material.
