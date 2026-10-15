# Architecture Decision Records

One page per decision: what we chose, what we rejected, and why. Written to be read in
under a minute.

## Index

| # | Decision | Status |
|---|---|---|
| [0001](0001-modular-monolith.md) | Modular monolith (`api` + `worker`), not microservices | Accepted |
| [0002](0002-event-source-order-only.md) | Event-source transactional aggregates (`Order`, `Shipment`, `Invoice`); reference/config stays CRUD | Accepted (amended by 0014) |
| [0003](0003-erp-adapter-registry.md) | ERPs plug in via an adapter + registry pattern, not per-ERP conditionals | Accepted (amended by 0021) |
| [0004](0004-single-shared-postgres.md) | One shared Postgres for event store + outbox + projections + CRUD | Accepted |
| [0005](0005-tenant-erp-identity-binding.md) | Tenant↔ERP identity resolved by a binding table, not an identity-resolution service | Accepted |
| [0006](0006-stateless-adapter-multi-instance.md) | Multiple instances of one ERP handled as data, not as separate adapter code | Accepted |
| [0007](0007-async-outbox-reconciliation.md) | Async delivery to ERPs via outbox + queue, with polling as the fallback safety net | Accepted |
| [0008](0008-graphql-split-by-audience.md) | Separate GraphQL schemas for reseller vs. operator | Accepted |
| [0009](0009-single-identity-provider.md) | One identity provider (Cognito) for both human and machine-to-machine auth | Accepted |
| [0010](0010-worker-role-split.md) | Split `worker` into independently-scalable roles | Accepted |
| [0011](0011-catalog-price-source.md) | Order line price is resolved from the catalog, never trusted from the client | Superseded by 0016 |
| [0012](0012-generic-connection-credentials.md) | ERP connection credentials are a generic bag, not fixed `database`/`username` fields | Accepted |
| [0013](0013-flat-item-tax-and-discount.md) | Tax and discount are flat per-item catalog fields, same source as price | Superseded by 0016 |
| [0014](0014-orthogonal-fulfillment-invoice-status.md) | Fulfillment/invoice status is derived and orthogonal to order lifecycle state. `Payment`/`Return` later removed | Accepted (amended) |
| [0015](0015-erp-capabilities-declared-not-gated.md) | `ErpCapabilities` is declared now, gated later (once a 2nd adapter exists) | Accepted |
| [0016](0016-price-from-quote-not-catalog.md) | Price lives on the quote, not the catalog; an order replies to a quote | Superseded on the live path by 0019 |
| [0017](0017-module-grouping-and-fulfillment-split.md) | Group modules by subdomain (`sales`/`reference`/`integration`); split `fulfillment` into `shipment` and `invoicing` (`payments`/`returns` later removed) | Accepted (amended) |
| [0018](0018-shipment-invoice-order-saga.md) | Shipment/invoice → order is an event-driven saga, not a cross-aggregate transaction | Accepted (supersedes FR-A4's atomic guarantee) |
| [0019](0019-order-routing.md) | An existing ERP order is routed by the connection being read and the verified binding on it | Accepted |
| [0020](0020-terraform-aws-deploy-and-cicd.md) | Terraform + AWS (single `staging` env, public for debugging) provisioned from GitHub Actions over OIDC | Accepted |
| [0021](0021-connections-before-adapters.md) | An ERP connection can exist before its adapter does; `hasAdapter` is derived, not stored | Accepted |
| [0022](0022-mapping-dedupe-by-erp-type.md) | Mapping/codegen is deduped per ERP type (registry + pending-job check), not per connection | Accepted |
| [0023](0023-azure-migration.md) | Migrate infrastructure off AWS onto Azure, service-for-service, behind the existing ports | Proposed |

## How to read one

Each ADR has the same shape, meant to be skimmed top to bottom in under a minute:
- **In one sentence** — the whole decision, before you read anything else
- **Why this needed a decision** — the problem, as a short table
- **The decision** — what we picked
- **Alternatives considered** — what else we looked at and why it lost
- **Consequences** — what this costs us, not just what it buys us (✅/⚠️ table)
- **Revisit when** — the condition that would make us reopen this

## Quick answers for "why isn't this X"

| Question | Short answer | Detail |
|---|---|---|
| Why not microservices? | One team, one ERP live, no independent-scaling pressure yet | [0001](0001-modular-monolith.md) |
| Why not event-source everything? | Most modules are lookup/CRUD data with no meaningful history to replay | [0002](0002-event-source-order-only.md) |
| Why not a database per module? | No operational need yet; layering is enforced by `import-linter`, not by network boundaries | [0004](0004-single-shared-postgres.md) |
| Why no dedicated "identity resolution" service? | Only two relationships ever need resolving (tenant↔ERP-customer, item↔connection); both are 1:1 and DB-constraint-enforceable | [0005](0005-tenant-erp-identity-binding.md) |
