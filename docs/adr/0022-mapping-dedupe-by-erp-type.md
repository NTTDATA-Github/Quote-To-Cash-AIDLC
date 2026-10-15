# ADR-0022: Mapping/codegen approval is deduped per ERP type, not per connection

| | |
|---|---|
| Status | Accepted |
| Affects | `integration.mapping` module, operator GraphQL/UI |

## In one sentence
Submitting a mapping job — and therefore generating a new adapter PR — is blocked for
any `erp_type` that already has a working adapter *or* an in-flight/approved mapping job
for that same type, regardless of which connection triggered it, so a second instance of
an already-mapped ERP can never kick off a redundant codegen run.

## Why this needed a decision

| Problem | Detail |
|---|---|
| One adapter already serves every connection of its type (ADR-0006) — but nothing stopped a second mapping job | `MappingJob.erp_name` was free text with no link to `ErpConnection.erp_type` at all (before ADR-0021 connected mapping to a real connection); the mapping → approve → codegen flow had no concept of "this ERP type already has, or is already getting, an adapter." |
| Checking "does an adapter already exist" (`hasAdapter`, ADR-0021) is necessary but not sufficient on its own | `hasAdapter` only becomes true once generated code is merged *and deployed*. Between "operator clicks Approve" and "PR merged," `hasAdapter` is still false for that `erp_type`. A second operator — or the same one, forgetting — could start a second mapping job for the same type in that exact window, producing a second, redundant PR for an ERP that already has one on the way. This was identified by direct review before being designed around, not discovered after the fact. |

## The decision
Submitting a mapping job for a given `erp_type` is rejected if **either** is true:

1. `hasAdapter(erp_type)` — the adapter registry (ADR-0003/0021) already has a working
   adapter for it, **or**
2. there is already a `MappingJob` for that `erp_type` in a non-rejected,
   not-yet-superseded state: `PENDING`/`PROCESSING`, or `DONE` with `adapter_run_id`
   already set (approved — even before the resulting PR merges).

Neither check alone is sufficient: (1) misses the approve-to-merge window described
above; (2) misses an adapter that reached the registry by any path other than this
mapping flow (e.g. a hand-written adapter merged directly, like Odoo/NetSuite today) —
the registry stays the ground truth for "does code exist," the job table is the ground
truth for "is someone already working on it."

The Mapping page's ERP selector follows directly: a dropdown of existing
`ErpConnection`s filtered to `hasAdapter == false` and no blocking job per check (2) —
never a free-text field. Picking a connection reads its already-stored
`base_url`/`credentials`/`secret_ref` (ADR-0021); nothing is retyped. The moment a
mapping job for an `erp_type` is submitted, **every** connection sharing that
`erp_type` drops out of the dropdown together — not only the one connection used to
probe it.

## Alternatives considered

| Option | Rejected because |
|---|---|
| Only check `hasAdapter` (the code registry) | Misses the approved-but-not-yet-merged window — a real gap, confirmed before this ADR was written, not a theoretical one |
| Only check "is there a pending/approved job" (no registry check) | Doesn't cover an adapter added by a path other than this mapping flow — the registry is still the only ground truth for "does code exist right now" |
| A database `UNIQUE` constraint on `mapping_jobs.erp_type` while non-terminal | Viable, but a bigger schema commitment than today's volume needs. An application-level check — the same pattern `BindingService` already uses (pre-check in code, DB conflict as defense-in-depth) — is enough at today's scale |

## Consequences

| | |
|---|---|
| ✅ | The exact regression this was designed against — a new instance of an already-mapped ERP silently kicking off another codegen run — is closed by two independent checks, not one |
| ✅ | The dropdown-only UX means an operator never sees a path to accidentally retrigger mapping for an ERP that already works |
| ✅ | Adding a genuinely new ERP stays a 3-touch-point change (status mapper, adapter class, registry line — ADR-0003 minus the enum member removed by ADR-0021), with no new step added by this decision |
| ⚠️ | The "pending job" check is a point-in-time service-layer scan, not a DB constraint — a true race (two submissions in the same instant) is not impossible, only very unlikely at today's volume. Same risk shape `BindingService` already accepts, not a new one |
| ⚠️ | An abandoned/rejected mapping job's probe secret (ADR-0021) still becomes orphaned Secrets Manager state — unchanged from before this ADR, not newly introduced |

## Revisit when
Submissions actually happen concurrently enough in practice that the race window in the
second ⚠️ matters — add a DB-level uniqueness constraint at that point, not before.
