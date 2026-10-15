# Frontend Components — U4 Admin & Configuration

**New 2026-10-15.** This artifact didn't exist before — the unit's original Functional
Design pass never documented the UI side. Written against the real components in
`ui/src/features/admin/` and `ui/src/hooks/{useAdmin,useMapping}.ts`, not a proposal.

Relationship to `design/`: that folder's two newest proposals (`connections.mock.html`,
`mappings-workspace.mock.html`) describe a different "mappings" concept (reseller
customer-links + item ownership) than what exists — see `design/proposals/README.md`'s
updated status note. This file is the current source of truth for these two screens;
`design/` is kept for its component-level rules (badge roles, button variants, table
density) which are still followed.

## Component hierarchy
```
AppShell (ui/src/App.tsx)
  Settings nav group: ERP connections, Subsidiaries, Resellers, ERP mapping
    ConnectionsPage          /admin/connections
    MappingsPage              /admin/mappings
    TenantsPage               /admin/tenants   (reseller name field added this pass)
```

## `ConnectionsPage`
**Purpose**: register every ERP connection — a known type (Odoo) or a brand-new one —
and show each one's live/paused status and whether it has a working adapter.

**State**: `adding: "odoo" | "custom" | null`; `odooForm` (`instanceLabel`, `baseUrl`,
`database`, `username`, `password`); `customForm` (`erpType`, `instanceLabel`, `baseUrl`);
`authType` (`AuthType`), `authHeaderName`, `authUsername`, `authSecret`; `search`,
`status` filter.

**Interaction flow**:
1. Pick a provider card — "Odoo" (tailored form: database/username/password, since the
   real adapter's auth shape is already known) or "New ERP" (generic form: ERP name,
   base URL, an `AuthType` select with conditional fields, one secret).
2. Submit → `useRegisterConnection()` → `registerConnection` mutation. The raw secret is
   sent once and never redisplayed (BR-U4-3).
3. The connection list (cards, one per `ErpConnection`) shows a live/paused `StatusBadge`
   and a derived "Adapter ready" / "Needs mapping" `erp-badge` from `hasAdapter`.
4. Pause/Resume per card → `usePauseConnection()` / `useResumeConnection()`.

**Form validation**: HTML `required` on every field the mutation needs; the secret field
is required unless `authType === "NONE"`.

**API integration points**: `connections` query (list), `registerConnection`,
`pauseConnection`, `resumeConnection` mutations — all in `ui/src/hooks/useAdmin.ts`.

## `MappingsPage`
**Purpose**: onboard a brand-new ERP type — pick an eligible connection, get its fields
matched against the platform's canonical order fields, review the LLM's proposal, approve
it to generate the adapter. A 4-step guided flow (`Stepper`), not a single form, because
unlike every other admin list this is a multi-stage pipeline with a real waiting step
(the LLM call) in the middle.

**State**: `connectionId` (selected); canonical-field source (`source`: registered /
one-off / new) and its fields; sample source (`sampleSource`: files / live) and its
fields (`sampleFiles`, `liveRequests`, `probePreview`); `jobId` (pins the Review/Approve
sections to a specific job); `approved`.

**Interaction flow**:
1. **Connect** — `ConnectionPicker` renders cards from `useMappableConnections()`
   (BR-U4-4's eligibility already applied server-side — the list never offers a
   connection that would just be rejected). Empty state links to `/admin/connections`.
2. **Canonical fields** — pick a saved schema, paste/upload a one-off CSV, or save a new
   named schema (`useRegisterCanonicalSchema`).
3. **ERP exposed fields** — upload sample files (`useSubmitMapping`) or pull them live
   from the selected connection (`useProbeErpSamples` for a preview, then
   `useSubmitMappingFromProbe` to commit). The live path sends no base URL or auth — only
   `connectionId` + the sample-request list; the connection already has that stored.
4. **Review** — `mapflow` rows (ERP field → canonical field, confidence tier) for the
   selected job, polled via `useMappingJobs()`/`useAdapterRun()` while running.
5. **Approve** — `useApproveMapping()`. The button disables once already approved; a
   rejection here (BR-U4-4's approve-time check) surfaces as a callout, same place
   `submit`'s rejection would.

**Form validation**: submit is disabled until a connection is selected, canonical fields
are ready, and (files or live) samples are present (`canSubmit`).

**API integration points**: `mappableConnections`, `canonicalSchemas`, `mappingJobs`,
`mappingJob`, `adapterRun` queries; `registerCanonicalSchema`, `submitMapping`,
`probeErpSamples`, `submitMappingFromProbe`, `approveMapping` mutations — all in
`ui/src/hooks/useMapping.ts`.

## `TenantsPage` (reseller name — this pass's addition only)
The existing binding-creation form gained a required **Reseller name** field (sent via
`createBinding`'s `name` argument, landing in the new `Reseller` entity) and the table's
"Reseller" column now shows that name instead of the raw `tenant_id`, with the raw id
still visible as a `Reseller ID` column. No other change to this page.

## Not covered here (unchanged by this pass)
`OverviewPage`, `OrdersPage`, `NotificationsPage`, `FailedMessagesPage`,
`OrderDetailPage`, `OrderEventsPage`, `SubsidiariesPage` — all pre-existing, read-mostly
admin screens with no business-logic change in this increment.
