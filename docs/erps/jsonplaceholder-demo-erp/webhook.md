# JSONPlaceholder Demo ERP inbound webhook

There is none. The poll still runs — see [supply-chain-check.md](./supply-chain-check.md).

## Why it looks like this

Neither of this platform's two webhook shapes (HMAC, or shared-secret-in-path) applies,
because JSONPlaceholder's public API has no automation/trigger feature at all — nothing
in it can be configured to call back out to this platform on a change (there is no
server-side state to change in the first place; see
[README.md](./README.md#known-gaps)). `ErpConnection.webhook_secret_ref` is left `None`
for every `JSONPLACEHOLDER_DEMO_ERP` connection.

Per `docs/adding-an-erp.md`: "Neither is required: every registered ERP gets
reconciliation polling regardless." `fetch_status`/`fetch_partner_orders` are what move
an order forward for this ERP — see
[README.md](./README.md#status-mapping) for exactly what `fetch_status` can and can't
tell the sweeper today.

## Secret

Not applicable — there is no webhook to sign or secret-check.

## What the ERP sends

Nothing. `erp_event_inbox` stays empty for every `JSONPLACEHOLDER_DEMO_ERP` connection.

## Prove a row landed

It won't — there's no inbound route to hit for this ERP type. To prove the *poll* path
instead, see [supply-chain-check.md](./supply-chain-check.md).
