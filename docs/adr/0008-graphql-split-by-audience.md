# ADR-0008: Separate GraphQL schemas for reseller and operator

| | |
|---|---|
| Status | Superseded — the reseller schema was removed; see note below |
| Affects | `src/api/graphql` |

## Update (operator console: generic connections, webhook auth, operator-only API)
`src/api/graphql/reseller` (schema + types) was removed; `/graphql/operator` is now the
only GraphQL schema the API serves. The two-schemas-by-audience split this ADR decided
is no longer the live architecture — resellers are served through webhooks, not
GraphQL. The structural guarantee below (no reseller-facing code path can return ERP
identity) still holds, just by having no reseller schema at all rather than by having a
second, deliberately narrower one. Kept for history; do not treat "Accepted" below as
current.

## In one sentence
Resellers and operators get two entirely separate GraphQL schemas, not one schema with
role-based field hiding — so there's no field that can be forgotten to guard.

## Why this needed a decision

| Problem | Detail |
|---|---|
| Resellers and operators need different views of the same data | Operators can see which ERP connection an order routes to |
| Leaking ERP identity to a reseller is a hard requirement to prevent | Not a nice-to-have — it would expose internal routing/business structure |

## The decision
Two GraphQL schemas, `/graphql/reseller` and `/graphql/operator` — not one schema with
per-field, role-based access checks at resolve time.

## Alternatives considered

| Option | Rejected because |
|---|---|
| One schema, hide fields by role at resolve time | A single missed authorization check on one field leaks ERP identity to a reseller — the failure mode is silent and easy to introduce by accident |
| Two schemas | Chosen: ERP identity fields simply don't exist in the reseller schema — there's no field to forget to guard |

## Consequences

| | |
|---|---|
| ✅ | Structural guarantee, not a runtime check — the reseller schema has no code path that can return ERP identity, because the type doesn't exist there |
| ✅ | Each schema can evolve independently — adding an operator-only field never risks a reseller-facing regression |
| ⚠️ | Any type that's genuinely shared (e.g. order status) has to be defined twice, once per schema — some duplication to maintain |

## Revisit when
The duplication between schemas becomes a real maintenance cost (not yet, at 2 schemas).
