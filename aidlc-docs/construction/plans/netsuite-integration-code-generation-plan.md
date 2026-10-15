# Code Generation Plan — U3-netsuite-integration

Single source of truth for the NetSuite increment. Brownfield: modify existing files
in-place; create new files only where noted. Application code at workspace root (never in
`aidlc-docs/`). Approved by user directive ("Follow AIDLC and build it").

## Steps

- [x] **Step 1 — Settings.** Add `erp_netsuite_timeout_seconds` to `Settings` +
  `get_settings()` (`src/shared/config/settings.py`). Env `ERP_NETSUITE_TIMEOUT_SECONDS`
  (default 10). *(done in earlier turn; verify)*
- [x] **Step 2 — ErpType.** Add `NETSUITE = "NETSUITE"` to `ErpType`
  (`src/modules/reference/connections/domain/models.py`).
- [x] **Step 3 — Status mapper.** Add `_map_netsuite` + `"NETSUITE"` entry to
  `STATUS_MAPPERS` (`src/modules/integration/erp/domain/status_mapping.py`).
- [x] **Step 4 — Adapter.** Create
  `src/modules/integration/erp/infrastructure/netsuite_adapter.py` — `NetSuiteAdapter`
  implementing `ErpAdapter`, TBA OAuth1 signing, stdlib HTTP, pure helpers, idempotency,
  fail-closed resolution, SuiteQL reads, record transforms, error classification.
- [x] **Step 5 — Registry.** Add `"NETSUITE": NetSuiteAdapter(...)` to
  `build_adapter_registry` (`src/modules/integration/erp/infrastructure/registry.py`).
- [x] **Step 6 — Fix Settings constructors.** Add the new field to the two direct
  `Settings(...)` builds in tests (`tests/integration/test_postgres_composition.py`,
  `tests/integration/test_mapping_graphql.py`).
- [x] **Step 7 — Mock server.** Create `scripts/mock_netsuite.py` — faithful stdlib
  SuiteTalk REST mock (reusable handler factory + `main()`), seeded items/customers.
- [x] **Step 8 — Unit tests + PBT.** Create
  `src/modules/integration/erp/tests/test_netsuite_adapter.py` (helpers, OAuth header,
  idempotency, fail-closed, fetch_status/shipments/invoices shaping) and status-mapper
  PBT in `test_status_mapping.py` (or the new file).
- [x] **Step 9 — Integration test.** Create
  `tests/integration/test_netsuite_adapter_against_mock.py` — real adapter end-to-end over
  OAuth-signed HTTP against the in-process mock on a loopback ephemeral port.
- [x] **Step 10 — Docs + local.sh.** Create `docs/erps/netsuite/{README,webhook,supply-chain-check}.md`
  from `_template`; update `docs/adding-an-erp.md` intro and root `README.md` table; start
  the mock in `scripts/local.sh`.
- [x] **Step 11 — Quality gates.** `ruff format` + `ruff check` clean, `lint-imports`
  0 broken, `APP_PROFILE=memory pytest src tests` green. Record results in aidlc-state.md.

## Story traceability
FR-NS-1 → Steps 4,5. FR-NS-2 → Step 4 (OAuth1). FR-NS-3 → Step 3. FR-NS-4 → Steps 1,2,5.
FR-NS-5 → Step 7. FR-NS-6 → Step 4. FR-NS-7 → Step 10. Resiliency → Step 4. PBT → Step 8.
Verification → Steps 9,11.
