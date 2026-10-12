# ERP knowledge base

One folder per ERP. The same three files every time, so a second ERP is a copy of `_template/` rather than a new shape.

| File | What it is |
|---|---|
| `README.md` | How this ERP's API, login, and documents map onto the adapter. |
| `webhook.md` | How it pushes a status change, and how to see the raw body in `erp_event_inbox`. |
| `supply-chain-check.md` | The clicks a developer performs to follow one order from creation through delivery and invoice. |

Generic steps that are the same for every ERP stay outside this folder:

- [adding-an-erp.md](../adding-an-erp.md) — the four code touch points.
- [erp-integration-patterns.md](../erp-integration-patterns.md) — webhook shapes and how instances and tenants stay apart.
- [adr/0019-order-routing.md](../adr/0019-order-routing.md) — which data routes an order, and when it is read.

## Folders

| ERP | Status | Folder |
|---|---|---|
| Odoo | Live | [odoo/](./odoo/supply-chain-check.md) |
| NetSuite | Not registered | — |
| SAP | Registered, not yet verified against a live system | [sap/](./sap/supply-chain-check.md) |

## Adding an ERP's folder

1. Copy `_template/` to `<erp>/`.
2. Fill the three files from that ERP's adapter and one real sandbox order.
3. Add a row to the table above.

`odoo.md` at the top of this folder is a pointer to `odoo/`. Do not add a new ERP as a single file.
