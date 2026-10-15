# Business Rules — U4 Admin & Configuration

**Updated 2026-10-15** (supersedes the original MVP-era rules below the line).

## BR-U4-1: Authorization
- All admin operations require the OPERATOR role (U1, Cognito `cognito:groups`). Missing
  the role raises, same as before this update — unchanged.

## BR-U4-2: `erp_type` is open, not a closed enum (ADR-0021)
- Any string is accepted, normalized to uppercase + trimmed on write, so "Shopify",
  "shopify" and "SHOPIFY " are always the same ERP for every rule below.
- A connection may be registered whether or not a working adapter exists for its type yet.
- "Has a working adapter" (`hasAdapter`) is derived from the adapter registry at read
  time — never a stored column, never a precondition for creating the connection row.

## BR-U4-3: Connection secrets are always generated, never hand-pasted
- `registerConnection` takes a raw credential (`auth.secret`); the backend writes it to
  Secrets Manager and stores only the resulting ref. There is no `secretRef` input.
- Exception: `auth_type = NONE` has nothing to protect, so Secrets Manager is skipped
  entirely rather than rejecting an empty value — `secret_ref` is the empty string, which
  every reader already treats as "no secret" (falsy).

## BR-U4-4: Mapping eligibility — two independent checks, both required (ADR-0022)
A connection's `erp_type` may start (or have approved) at most one mapping job at a time:
1. **Registry check** — rejected if `hasAdapter(erp_type)` is already true.
2. **Job-state check** — rejected if another job for that `erp_type` is `PENDING`/
   `PROCESSING`, or `DONE` with `adapterRunId` already set (approved).

Neither check alone is sufficient:
- The registry check alone misses the window between "operator approves" and "the
  generated adapter actually merges and deploys" — `hasAdapter` is still false there.
- The job-state check alone misses an adapter that reached the registry by any path other
  than this mapping flow (a hand-written adapter merged directly, as Odoo/NetSuite were).

**Both checks run twice**, not once: at *submission* (`submit_job`/`submit_job_from_probe`
— also catches a merely-pending/unreviewed sibling, avoiding a second wasted LLM-proposal
run) and again at *approval* (`approve` — the actual code-generation trigger, and the one
place two jobs that both reached DONE-unapproved before either was reviewed are stopped
from both being approved).

## BR-U4-5: Manual sample upload is the universal fallback
`submitMapping` (file upload) is subject to the exact same BR-U4-4 eligibility check as
`submitMappingFromProbe`, but never requires a particular `auth_type` — it is the one path
that works for any ERP's auth, however exotic, so no ERP is ever blocked from onboarding.

## BR-U4-6: Outbound probe calls are SSRF-guarded
Every URL `GenericErpProbe` dials (the connection's `base_url`, built from operator-typed
input that hasn't been vetted by anyone yet) is checked against private, loopback,
link-local and cloud-metadata address ranges before the request is made. A connection
already in production use for real delivery is a different, already-vetted trust level and
is not re-checked here.

## BR-U4-7: Reseller `name` is separate from `tenant_id`
- `tenant_id` never changes meaning and is never replaced by `name` — it stays the stable
  key used in RLS policies, Cognito's `custom:tenant_id`, and webhook URLs.
- `name` is pure display metadata (`createBinding`'s `name` argument, or `renameReseller`
  on its own) and carries no authorization or routing weight.

## BR-U4-8: Config is platform-scoped
Unchanged from the original model: admin data is governed by OPERATOR authorization, not
tenant row-filtering (consistent with U0's tenant-scoping rule for everything that *is*
tenant data).

---

## Superseded (original MVP-era rules, kept for history — do not build against this)

### BR-U4-2 (old): Instance Registration (US-6.1)
- erp_type must be a supported type (ERP_NEXT, ODOO for MVP); connection_ref required.
- Invalid/incomplete details -> validation error, nothing persisted.
- Connectivity check reports reachable/unreachable via the adapter (stub returns reachable).

### BR-U4-3 (old): Routing Rules (US-6.2)
- target_instance_id must reference an existing active instance (BR-4.3).
- order_index defines precedence; reorder sets it explicitly.
- Overlapping rules are allowed; first-match-wins by order_index at runtime (U0/U3).

This never shipped: routing is decided at quote-issue time from the issuing subsidiary's
current route (ADR-0019), not a first-match-wins rule table.

### BR-U4-4 (old): Mappings (US-6.3)
- MappingDefinition must reference an existing instance.
- Required canonical fields without a mapping entry are reported as warnings.

Superseded by the real mapping feature (BR-U4-4/U4-5 above), which is LLM-proposed and
human-reviewed, not admin-authored field entries.
