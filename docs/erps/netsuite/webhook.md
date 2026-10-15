# NetSuite inbound webhook

**Not set up — NetSuite runs polling-only today.** The reconcile sweeper
(`fetch_status`/`fetch_shipments`/`fetch_invoices`, every `RECONCILE_INTERVAL_SECONDS`,
default 15 min) keeps a NETSUITE order correct without any webhook. The walk that proves
the whole flow is [supply-chain-check.md](./supply-chain-check.md).

## Why it looks like this

NetSuite's push options (SuiteScript user-event scripts / workflow actions calling an
external URL) are **thin**: they realistically send an id and "something changed", not the
new status. Our inbound path (`webhooks_inbound/application/ingress.py`) cannot yet call
back into the ERP to fetch the real record, so a thin payload authenticates and is stored
but produces no transition (`map_native_status` sees no usable status) — it degrades to
polling, it does not break. This is a scope decision, documented in
`docs/erp-integration-patterns.md` (§"thin webhook"), not a limitation of the adapter:
`fetch_status` already exists and is exercised by the sweeper.

If/when the thin fast-path is wired (give the ingress an `adapter_for` + `ConnectionResolver`,
and on an empty status call `fetch_status` before mapping), NetSuite would use the **HMAC**
route (`POST /erp/webhook/{connection_id}`, header `x-erp-signature`) — a SuiteScript can
compute an HMAC over the body, unlike Odoo's automation rules.

## Secret

Would be `webhook_secret_ref` on the connection — never the TBA login secret in `secret_ref`.
Unset today.

## What the ERP sends

N/A today (polling-only). A future thin payload would carry at least the record id
(`erp_order_id`) and an event marker; the status itself would be fetched, not trusted from
the body.

## Prove a row landed

N/A today — there is no inbound webhook for NetSuite yet. Use the poll path in
[supply-chain-check.md](./supply-chain-check.md) instead.
