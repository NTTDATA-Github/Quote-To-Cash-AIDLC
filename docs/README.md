# Documentation

Start with the guide for your role. Each one is self-contained and links to the deeper
reference material when you need it.

| You are a… | Read | It answers |
|---|---|---|
| **Product owner / stakeholder** | [product-owner-guide.md](product-owner-guide.md) | What the product does, every feature it supports, the constraints, and what it deliberately does *not* do yet. |
| **Business reader** | [business-case.md](business-case.md) | The whole flow in plain language: who is registered first, how a quotation reaches the reseller, and how a later purchase order would use the same records. |
| **Scoping a demo** | [erp-scope-answers.md](erp-scope-answers.md) | Which ERP, which documents we follow, the fields those documents must carry, and whether the demo needs a UI. |
| **Developer** | [developer-guide.md](developer-guide.md) | The whole data flow traced end to end — the exact order payload, every event, what changes at each step, status conversions, and the notifications sent out. |
| **Architect** | [architecture-guide.md](architecture-guide.md) | How the system is shaped: modules, runtime, the consistency model, how to extend it to new ERPs, and why the big decisions were made. |

## Reference (linked from the guides, read when you need the detail)

- **[adr/](adr/README.md)** — the decision log: one page per significant decision (what we
  chose, what we rejected, why). The architecture guide points you at the relevant ones.
- **[architecture/hld.md](architecture/hld.md)** — the C4 container diagram and the
  component/data-ownership tables (diagram source: `architecture/hld.drawio`).
- **[database-schema.md](database-schema.md)** — every table and column.
- **[state-machines-and-lifecycles.md](state-machines-and-lifecycles.md)** — every stateful
  lifecycle in the code: the `Order` state machine (states, guarded transitions, orthogonal
  fulfillment/delivery/invoice dimensions) plus the record-only aggregates and the CRUD
  status lifecycles (quote, mapping job, connection, binding, outbound webhook delivery).
- **[event-sourcing-explained.md](event-sourcing-explained.md)** — a plain-language primer
  on why the transactional aggregates are stored as events (and why reference data isn't).
- **Integration**
  - **[adding-an-erp.md](adding-an-erp.md)** — the checklist to onboard a new ERP type.
  - **[erp-integration-patterns.md](erp-integration-patterns.md)** — webhook shapes
    (rich vs. thin), and how multiple ERP instances/tenants stay untangled.
  - **[erps/](erps/README.md)** — one folder per ERP (`README.md`, `webhook.md`, `supply-chain-check.md`).
  - **[erps/odoo/supply-chain-check.md](erps/odoo/supply-chain-check.md)** — Odoo clicks that prove one order end to end.
- **Operations**
  - **[local-setup.md](local-setup.md)** — run the whole stack locally with no cloud account.
  - **[git-hooks.md](git-hooks.md)** — the pre-commit quality gate.

> The `aidlc-docs/` tree is a separate thing: it's the AI-DLC process ledger (requirements,
> design trail, per-increment state, audit log), not product documentation. Read it only if
> you care about *how* the system was built increment by increment.
