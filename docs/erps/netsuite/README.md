# NetSuite

Status: **live** (registered). Adapter file:
`src/modules/integration/erp/infrastructure/netsuite_adapter.py`.
If this page disagrees with that file or `status_mapping.py`, the code is right.

A faithful in-process **mock** NetSuite (`scripts/mock_netsuite.py`) speaks the same
SuiteTalk REST dialect, so the adapter runs end-to-end with no live account; switching to a
real NetSuite is `base_url` + the secret only (see "How a connection is configured"). The
end-to-end proof is `tests/integration/test_netsuite_adapter_against_mock.py`.

## What it is, as far as this platform is concerned

The sales order is NetSuite's `salesOrder` record, over **SuiteTalk REST Web Services**
(`/services/rest/record/v1/...`). Reads that need joins/filters use **SuiteQL**
(`POST /services/rest/query/v1/suiteql`). The adapter never creates customers or items; it
references them.

## How a connection is configured

| `ErpConnection` field | What it is for NetSuite |
|---|---|
| `base_url` | Account-specific REST domain, `https://<ACCOUNT_ID>.suitetalk.api.netsuite.com` (mock: `http://127.0.0.1:8075`). |
| `credentials` | Non-secret bag the adapter reads: `account_id` (the TBA realm), `consumer_key`, `token_id`. |
| `secret_ref` | A Key Vault ref whose value is **JSON** `{"consumer_secret": "...", "token_secret": "..."}` — the two secret TBA components. A malformed/empty secret is a terminal error. |
| `webhook_secret_ref` | Unused today — NetSuite runs polling-only (see [webhook.md](./webhook.md)). |

The single-secret-holds-JSON choice is deliberate (requirements D-NS-2): it keeps NetSuite
inside the existing one-secret connection contract with no schema change.

## Authentication

Token-Based Authentication: **OAuth 1.0a, HMAC-SHA256** (NetSuite dropped HMAC-SHA1 in
2023.1). Every request is signed with four credentials — `consumer_key`/`consumer_secret`
and `token_id`/`token_secret` — and the account id as the OAuth `realm` (upper-cased). The
signing is a pure, unit-tested function (`oauth1_authorization_header`) and is
independently re-verified by the mock. A bad credential returns `401`, which the adapter
classifies **terminal** (no retry); timeouts/`5xx`/connection errors are transient (retry via
Service Bus redelivery).

## How an order arrives

This product does not create the sales order. `fetch_partner_orders` reads `salesOrder`
records for the customer via SuiteQL (`transaction WHERE type = 'SalesOrd' AND entity = <id>`).
The binding's `erp_customer_id` is NetSuite's own **customer internal id** (the salesOrder
`entity`). `product_key` is the item's `itemid` (SKU); a line whose SKU resolves to no
NetSuite item is a terminal error on submit (fail closed — no phantom item), and a read line
with no `itemid` is skipped.

## Status mapping

Reads the salesOrder `status` refName first, `orderStatus` code as fallback (both
lowercased/stripped by `map_native_status`). See `_map_netsuite` in `status_mapping.py`.

| Native fields | Canonical status |
|---|---|
| `status` = cancelled/canceled, or `orderStatus` = C | `CANCELLED` |
| `status` = billed / fully billed / closed | `CLOSED` |
| `status` = pending fulfillment / partially fulfilled / pending billing / pending billing/partially fulfilled | `CONFIRMED` |
| `status` = pending approval, or anything unrecognized | no transition |

## Shipments and invoices

`fetch_shipments` reads `itemFulfillment` documents created from the sales order
(`transaction WHERE type = 'ItemShip' AND createdfrom = <so id>`); the fulfillment `tranId`
is the proof of delivery. `fetch_invoices` reads `invoice` documents
(`type = 'CustInvc' AND createdfrom = <so id>`); the invoice `tranId` is the number. The
stable id across polls is each document's **internal id**. Fulfillment line quantities are
stored negative in NetSuite; the adapter returns their absolute value.

## Known gaps

- **Cancel.** NetSuite has no first-class REST "cancel order" action. The adapter deletes
  the sales order (standard for an unfulfilled order); a `404` is treated as already-gone. A
  fulfilled order can't be deleted and returns a terminal error.
- **Thin webhooks.** NetSuite's webhooks are thin (id + "changed"); the inbound path can't
  yet call back to fetch the real status, so a NETSUITE connection is polling-only. See
  [webhook.md](./webhook.md) and `docs/erp-integration-patterns.md`.
- Only verified against the in-process mock in this environment; a live-sandbox walk
  ([supply-chain-check.md](./supply-chain-check.md)) is the remaining real-world confirmation.
