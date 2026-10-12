# SAP

Status: **registered** (`ErpType.SAP`, adapter: `src/modules/integration/erp/infrastructure/sap_adapter.py`).
Built and unit-tested against mocked HTTP (`test_sap_adapter.py`), per SAP's own public
API documentation — **not yet exercised against a live SAP system**. If this page
disagrees with that file or `status_mapping.py`, the code is right and this page is
stale.

## What it is, as far as this platform is concerned

SAP's public **Sales Order (A2X) API** — `API_SALES_ORDER_SRV` (OData V2), entity
`A_SalesOrder` with its `to_Item` navigation to `A_SalesOrderItem` — is "the sales
order" here. Companion public APIs cover the two documents a sales order leads to:
`API_OUTBOUND_DELIVERY_SRV` (`A_OutbDeliveryItem`) for deliveries, and
`API_BILLING_DOCUMENT_SRV` (`A_BillingDocumentItem`) for invoices. All three are
separate OData service roots in a real SAP landscape, not one base URL.

## How a connection is configured

| `ErpConnection` field | What it is for SAP |
|---|---|
| `base_url` | The **Sales Order** OData service root, e.g. `https://<host>/sap/opu/odata/sap/API_SALES_ORDER_SRV` — no trailing slash; the adapter appends `/A_SalesOrder` etc. |
| `credentials["client_id"]` | OAuth 2.0 client-credentials client id (see Authentication). |
| `credentials["token_url"]` | Optional override for the OAuth token endpoint. Defaults to `<base_url>/oauth/token` if unset — an assumption, not a confirmed value for any real account. |
| `credentials["sales_order_type"]`, `["sales_organization"]`, `["distribution_channel"]`, `["organization_division"]` | SAP's mandatory sales-document org-structure fields. **Account-specific — `submit` fails closed (terminal) if any is missing.** No default is invented. |
| `credentials["outbound_delivery_service_url"]` | Service root for `API_OUTBOUND_DELIVERY_SRV`. Without it, `fetch_shipments` returns `[]` (see Known gaps). |
| `credentials["billing_document_service_url"]` | Service root for `API_BILLING_DOCUMENT_SRV`. Without it, `fetch_invoices` returns `[]`. |
| `credentials["rejection_reason_code"]` | This account's SAP-configured rejection reason code (e.g. `"08"`). Without it, `cancel` fails closed (terminal) rather than guessing a code. |
| `secret_ref` | Resolves to the OAuth client secret — paired with `credentials["client_id"]` in the client-credentials grant. |
| `webhook_secret_ref` | Unset for SAP today — see [webhook.md](./webhook.md). |

## Authentication

OAuth 2.0 **client-credentials grant** (`POST <token_url>`, `grant_type=client_credentials`
+ `client_id` + `client_secret`) — SAP's current recommended auth for system-to-system
integration against S/4HANA Cloud / BTP-fronted systems (Communication Arrangements), per
SAP's public API Business Hub docs, in preference to legacy Basic Auth straight against
the Gateway. **ASSUMPTION, from SAP's public API documentation, to be verified against
this account's real auth setup** — an on-prem Gateway reached without a BTP front door
might only offer Basic Auth, in which case `_oauth_token` needs a second code path.

Every state-changing call (POST/PATCH/PUT/DELETE) also fetches a **CSRF token** first
(`GET` with header `X-CSRF-Token: Fetch`, replayed on the next call along with the
session cookie) — a public, documented convention of the SAP Gateway OData framework
itself, implemented for real in `_csrf_token`/`_do_request`, not account-specific.

A missing/invalid credential (OAuth token request failing, or missing org-structure
credentials) is a **terminal** error — it will not resolve on retry without a
configuration change.

## How an order arrives

This adapter does not read "existing SAP orders a reseller already placed" any
differently than Odoo's pattern: `fetch_partner_orders` reads `A_SalesOrder` rows whose
`SoldToParty` is a verified binding's `erp_customer_id`, expanding `to_Item` for lines. A
line with no `Material` or no quantity is skipped — same "a line with no code is
skipped" rule as Odoo's.

## Outbound: canonical order → SAP `A_SalesOrder`

Field correspondence is the **human-reviewed, approved mapping** this adapter was built
against (see `sap_adapter.py`'s module docstring) — not re-derived here:

| Canonical | SAP field | Confidence | Notes |
|---|---|---|---|
| (returned) `erp_order_id` | `SalesOrder` | 95% | Read back after create. |
| our own `order_id` (idempotency key, FR-A2) **and**, separately, the reseller's `client_reference` | `PurchaseOrderByCustomer` | 95% (for `client_reference`) | **Dual use, like Odoo's `client_order_ref`:** written with *our* `order_id` on create and searched first (idempotency); read back as the reseller's own PO number on orders we did not create (`fetch_partner_orders`). The dual use itself is this adapter's own design, not part of the approved mapping. |
| `line.product_key` | `Material` | 95% | Direct passthrough — SAP's `Material` *is* the material master's key, unlike Odoo's internal numeric product id, so there is no separate lookup call. An unknown code is not resolved here; it fails closed via SAP's own OData validation error on create. |
| `line.quantity` | `RequestedQuantity` | 95% | Direct. |
| `line.unit_of_measure` | `RequestedQuantityUnit` | 95% | Direct passthrough — no name-lookup table was approved for this field (unlike Odoo's `uom.uom` search). |
| `line.unit_price` net of `line_discount` | `NetAmount` | **40% — LOW CONFIDENCE, approved anyway** | SAP's `NetAmount` is often the item's *pricing-procedure-computed* net value, not a literal per-unit price, and may be overridden by SAP's own condition records regardless of what is sent here. Flagged in code at every call site for a human reviewer. |
| binding `erp_customer_id` (FR-A1) | `SoldToParty` | — (not in the approved mapping; SAP's own documented field for "the customer") | Used directly, never a name-based lookup/auto-create — missing/invalid is terminal. |
| — | `SalesOrderType`, `SalesOrganization`, `DistributionChannel`, `OrganizationDivision` | — | Mandatory SAP org-structure fields. **Account-specific — read from `credentials`, never invented; `submit` fails closed if any is missing.** |

### `submit` — step by step

1. Get an OAuth token.
2. **Idempotency**: `GET /A_SalesOrder?$filter=PurchaseOrderByCustomer eq '<order_id>'`;
   if found, return its `SalesOrder` immediately.
3. **Customer**: `SoldToParty = erp_customer_id` from the verified binding, used
   directly. Missing/invalid → terminal error.
4. **Org structure**: read the four mandatory header fields from `credentials`; any
   missing → terminal error naming exactly which keys are absent.
5. **Per line**: `Material`/`RequestedQuantity`/`RequestedQuantityUnit` direct from the
   payload; `NetAmount` only if a `unit_price` was given (net of `line_discount`).
6. **Deep insert**: one `POST /A_SalesOrder` with the header fields and `to_Item.results`
   — SAP OData V2's standard create pattern for a document with lines.
7. Read back `SalesOrder` → our `erp_order_id`.

## Inbound: SAP status → canonical status

`status_mapping.py`'s `_map_sap(fields)` reads three header fields `fetch_status`
returns. **ASSUMPTION, from SAP's public `API_SALES_ORDER_SRV` documentation, to be
verified against a real account's `$metadata`:** these mirror the classic SD document
status concept (processing / billing / rejection status — historically
VBUK-`GBSTK`/`FKSTK`/`ABSTK`) under the public OData field names below. Not an
account-specific unknown — a reasoned default from SAP's own documented API shape, not
a blank placeholder.

| `overall_sd_document_rejection_status` | `overall_billing_status` | `overall_sd_process_status` | Canonical status |
|---|---|---|---|
| `C` (completely rejected) | *(any)* | *(any)* | `CANCELLED` |
| not `C` | `C` (completely invoiced) | *(any)* | `CLOSED` |
| not `C` | not `C` | `A`, `B`, or `C` | `CONFIRMED` |
| not `C` | not `C` | anything else / absent | *(no transition)* |

`fetch_status` does one `GET /A_SalesOrder('<id>')?$select=...` for all three fields in
a single call — same shape as Odoo's single `search_read` reading both `state` and
`invoice_status`.

`cancel` has no single SAP action analogous to Odoo's `action_cancel` — it sets
`ReasonForRejection` on every item via `PATCH /A_SalesOrderItem(...)`, using this
connection's `credentials["rejection_reason_code"]` (account-specific; fails closed if
unset — see Known gaps).

## Shipments and invoices

`fetch_shipments` reads `API_OUTBOUND_DELIVERY_SRV`'s `A_OutbDeliveryItem`, filtered by
`ReferenceSDDocument eq '<erp_order_id>'`, keeping only items whose delivery header
`GoodsMovementStatus` is `C` (goods issue posted — the SAP analogue of Odoo's "done"
picking). `erp_shipment_id` is the `DeliveryDocument` number, stable across polls.

`fetch_invoices` reads `API_BILLING_DOCUMENT_SRV`'s `A_BillingDocumentItem`, filtered by
`ReferenceSDDocument eq '<erp_order_id>'`, skipping credit memos
(`to_BillingDocument.SDDocumentCategory == "O"`). `erp_invoice_id` is the
`BillingDocument` number.

Both are **ASSUMPTIONs from SAP's public API documentation** (field/entity names), and
both return `[]` until this connection's `credentials` carry
`outbound_delivery_service_url` / `billing_document_service_url` — see Known gaps.

## Known gaps

Real limitations, not hidden:

- **`outbound_delivery_service_url` and `billing_document_service_url` are not
  guessable from the Sales Order service's `base_url`.** They live on different OData
  service roots, and exactly where they're reachable (API gateway, landscape, path)
  varies per account. `fetch_shipments`/`fetch_invoices` return `[]` — not an error —
  until these are added to a real connection's `credentials`.
- **The four org-structure credentials (`sales_order_type`, `sales_organization`,
  `distribution_channel`, `organization_division`) and `rejection_reason_code` are
  entirely account-specific SAP configuration.** `submit`/`cancel` fail closed
  (terminal) rather than invent a value — there is no "default" sales org that is
  correct for an arbitrary SAP system.
- **`NetAmount` is a LOW-CONFIDENCE (40%) approved mapping for `unit_price`.** SAP's own
  pricing procedures may recompute or ignore a client-supplied `NetAmount` depending on
  the account's pricing configuration — this is the single field in this adapter most
  worth a second look once a live account is available.
- **The OAuth client-credentials assumption is unverified.** An on-prem SAP Gateway
  reached without a BTP front door may only support Basic Auth; `_oauth_token` would
  need a second path for that case.
- **Not exercised against a live SAP system.** Everything above is built from SAP's
  public API documentation and unit-tested against a mocked HTTP seam
  (`test_sap_adapter.py`) — unlike Odoo, there is no local SAP container in
  `docker-compose.yml` to run a real end-to-end check against yet.
