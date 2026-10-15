# Business Logic Model — U4 Admin & Configuration

**Updated 2026-10-15** (supersedes the original MVP-era model below the line) to match
what is actually built and running: the operator GraphQL schema (`src/api/graphql/operator/`),
`ConnectionService`, `MappingService`, `BindingService`, and the reseller-naming service
exposed on `Container`. All operations require the OPERATOR role (U1's Cognito group).

## Process 1: Register an ERP connection (any `erp_type`, known or brand new)
`ConnectionService.register` — ADR-0021. A connection can be created for an ERP that
already has a working adapter (Odoo, NetSuite) or for one that doesn't yet; there is no
enum gate. Steps:
- Normalize `erp_type` (uppercase + trim) so the same real-world ERP is never recorded
  under two different spellings.
- Generate the connection id, then the secret: if a raw `secret` was given, write it to
  Secrets Manager under a fresh ref (`erp-connection/<connection_id>`) and store the ref;
  if no secret applies (`auth_type = NONE`), skip Secrets Manager rather than writing an
  empty value it would reject.
- Persist `ErpConnection` (credentials bag, secret ref, `auth_type` — read only by
  Process 3's probe, never by a real adapter) and publish `CONNECTION_REGISTERED`.

## Process 2: Pause / resume a connection
`ConnectionService.pause` / `resume` — unchanged from the original model. Stops/resumes
routing new deliveries through the connection (`ConnectionRepository.list_active`) without
deleting anything it's referenced by. Publishes `CONNECTION_PAUSED` / `CONNECTION_RESUMED`.

## Process 3: Onboard a brand-new ERP type (propose a field mapping, generate the adapter)
This is the actual "ERP mapping" feature — a schema/field mapping from a not-yet-adapted
ERP's exposed fields onto the platform's canonical order fields, reviewed by a human, then
handed to a code-generation service. It replaces nothing from the original model (which
described a `MappingDefinition`/admin-authored field-entry table that was never built this
way) — it's the real feature in its place. `MappingService`:

1. **Eligibility** (ADR-0022, two independent checks — see Business Rules): a connection
   may only start a new mapping job if its `erp_type` has no working adapter yet *and* no
   mapping job for that type is already in flight or approved.
2. **Get samples**, two ways:
   - **Live probe** (`probe_samples` / `submit_job_from_probe`) — fires one or more
     `SampleRequestSpec`s against the connection's own `base_url`, using its stored
     `auth_type`/`credentials`/`secret_ref` (nothing retyped). Every URL is checked by the
     SSRF guard first (operator-typed input, not yet a reviewed connection).
   - **Manual file upload** (`submit_job`) — the universal fallback for any auth shape the
     declarative probe strategies don't cover.
3. **Propose** — the `mapping` worker role claims PENDING jobs and calls the LLM
   (`MappingProposer`) to produce `MappingEntry` rows (ERP field → canonical field +
   confidence), unchanged mechanism from before this update.
4. **Review** — operator reads the proposal (no action here changes state).
5. **Approve** (`approve`) — re-checks eligibility *again*, independently of step 1, before
   handing the mapping to `erp-agent-service` (the actual adapter-codegen trigger). This
   second check exists because two jobs for the same `erp_type` can both reach "proposed"
   before either is reviewed; approving the first must not let the second one through too.

## Process 4: Manage resellers (name + ERP customer links)
- `BindingService.create_binding` (unchanged mechanism) links a reseller (`tenant_id`) to
  a connection + that reseller's customer id in that ERP.
- New: every reseller also gets a display `name` (`ResellerRepository.upsert`, called
  alongside `create_binding` and via a standalone `renameReseller`) — `tenant_id` stays the
  stable, opaque partition key used everywhere else (RLS, Cognito, webhook URLs); `name` is
  purely what the UI shows instead of the raw id.

## Process 5: View admin data
Read-only GraphQL queries: `connections` (each carrying a derived `hasAdapter`),
`mappableConnections` (Process 3's eligibility, pre-filtered for the picker), `resellers`,
`bindings`, `mappingJobs`/`mappingJob`, `adapterRun`, plus the existing orders/notifications/
failed-messages/overview queries (unchanged).

## Data Flow (GraphQL, operator schema)
```
registerConnection        -> Process 1
pauseConnection /
resumeConnection          -> Process 2
probeErpSamples           -> Process 3, step 2 (live, preview only — no job)
submitMapping /
submitMappingFromProbe    -> Process 3, steps 1-2 (eligibility, then create the job)
approveMapping            -> Process 3, step 5 (eligibility again, then hand off)
createBinding             -> Process 4 (binding + reseller name)
renameReseller            -> Process 4 (name only)
connections / mappableConnections /
resellers / mappingJobs /
mappingJob / adapterRun   -> Process 5
```
All guarded by `ctx.require_role("OPERATOR")`.

---

## Superseded (original MVP-era model, kept for history — do not build against this)

Minimal internal admin surface (JSON API for MVP). All operations require ADMIN role (U1). Manages the U0 config domain (ErpInstance, RoutingRule, MappingDefinition).

### Process 1: Register / Update ERP Instance (US-6.1)
- Validate details (erp_type in {ERP_NEXT, ODOO}, connection_ref present); persist instance; optional connectivity check via U3 adapter registry.

### Process 2: Define / Order Routing Rules (US-6.2 authoring)
- Create/update rule (order_index, conditions, target_instance_id, enabled); validate target references an active instance; reorder by supplying ordered ids.

### Process 3: Manage Mapping Definitions (US-6.3 authoring)
- Create/update MappingDefinition (instance, data_type, direction, field_entries); report unmapped required fields (mapping completeness, BR-4.4).

### Process 4: View Configuration (US-6.4)
- Return current instances, routing rules (ordered), and mappings.

This never shipped in this shape: routing is decided at quote-issue time from the issuing
subsidiary's current route (ADR-0019), not admin-authored ordered rules; there is no
generic `RoutingRule`/`RoutingCondition` table.
