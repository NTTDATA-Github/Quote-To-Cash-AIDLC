# SAP inbound webhook

How SAP could push a status change to us. **Not implemented for SAP today** — the poll
(`fetch_status`, `fetch_shipments`, `fetch_invoices`) is what currently moves a SAP-backed
order through the lifecycle, exactly as `docs/adding-an-erp.md` describes: inbound
webhooks are a separate, optional step, and every registered ERP already gets
reconciliation polling regardless. The walk that proves the poll works end to end is
[supply-chain-check.md](./supply-chain-check.md).

## Why there is nothing wired up yet

Unlike Odoo (Automation Rules can run Python that POSTs to us) or an ERP that can sign a
request body, SAP's standard Sales Order API has no single, universal "call this URL on
status change" feature available on every account out of the box. A real integration
would typically use one of:

- A custom ABAP ("BAdI"/user-exit) HTTP call on save, analogous to Odoo's Automation Rule
  — shared-secret-in-path (`POST /erp/webhook/{connection_id}/{webhook_secret}`), since
  ABAP code (like Odoo's) is not a natural place to compute an HMAC.
- **SAP Event Mesh** (BTP), if the account has it provisioned, which *can* carry a
  signature — the HMAC route (`POST /erp/webhook/{connection_id}`, header
  `x-erp-signature`) would fit that case.

Which of these (if either) is available, and how it is configured, is **account-specific
SAP landscape/BTP configuration** — not something this adapter's code can know or invent.

- TODO: once a real account's webhook mechanism (ABAP exit, Event Mesh, or none) is
  known, fill in this section with the real setup steps, picking the HMAC or
  shared-secret-in-path route per `erp-integration-patterns.md`, and set
  `webhook_secret_ref` on that connection.

## Secret

Not yet applicable — `webhook_secret_ref` is unset on every SAP connection today.

## What SAP would send

Not yet applicable. Once a webhook mechanism is chosen, this table should list the
fields `status_mapping.py`'s `_map_sap` reads: `overall_sd_process_status`,
`overall_sd_document_rejection_status`, `overall_billing_status` — plus the SAP
`SalesOrder` number so the matching platform order can be found.

## Prove a row landed

Not yet applicable — there is no SAP webhook route to curl against yet. Status currently
only arrives via the reconcile sweeper polling `fetch_status`.
