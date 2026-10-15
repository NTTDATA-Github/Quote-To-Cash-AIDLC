# Build and Test — U3-netsuite-integration

## What was built (brownfield; files modified in-place or created)

**Created**
- `src/modules/integration/erp/infrastructure/netsuite_adapter.py` — real NetSuiteAdapter
  (SuiteTalk REST, TBA OAuth 1.0a HMAC-SHA256), pure helpers, idempotency, fail-closed
  resolution, SuiteQL reads, record transforms, transient/terminal classification.
- `scripts/mock_netsuite.py` — faithful in-process SuiteTalk REST mock (dev-only, stdlib,
  not in `src/`); independently re-verifies the OAuth signature.
- `src/modules/integration/erp/tests/test_netsuite_adapter.py` — unit tests (helpers,
  OAuth header, idempotency, fail-closed, fetch_* shaping, malformed-secret, cancel).
- `tests/integration/test_netsuite_adapter_against_mock.py` — real adapter end-to-end over
  OAuth-signed loopback HTTP against the mock (submit → status → fulfill/invoice → reads →
  cancel), plus a bad-signature-rejected test.
- `docs/erps/netsuite/{README,webhook,supply-chain-check}.md`.

**Modified**
- `src/shared/config/settings.py` — `erp_netsuite_timeout_seconds`.
- `src/modules/reference/connections/domain/models.py` — `ErpType.NETSUITE`.
- `src/modules/integration/erp/domain/status_mapping.py` — `_map_netsuite` + registry entry.
- `src/modules/integration/erp/infrastructure/registry.py` — NETSUITE adapter registration.
- `src/modules/integration/erp/tests/test_status_mapping.py` — NetSuite mapping + PBT.
- `tests/integration/test_postgres_composition.py`, `tests/integration/test_mapping_graphql.py`
  — new Settings field (and backfilled two long-stale missing fields in the former).
- `scripts/local.sh`, `README.md`, `docs/erps/README.md`, `docs/adding-an-erp.md` — mock
  wired into local stack; ERP tables / intro updated to two registered ERPs.

## Quality gates (mandatory — all pass)

| Gate | Command | Result |
|---|---|---|
| Format | `ruff format --check src tests migrations scripts` | 254 files already formatted (stable) |
| Lint | `ruff check src tests migrations scripts` | All checks passed! |
| Architecture contracts | `lint-imports` | Contracts: 4 kept, 0 broken |
| Tests | `APP_PROFILE=memory pytest src tests -q` | 222 passed, 2 skipped |

The 2 skips are the pre-existing Postgres/floci integration tests that self-skip offline
(unrelated to NetSuite). The NetSuite subset (unit + mapping PBT + end-to-end-vs-mock) is
43 passed. UI gate N/A (no `ui/` change).

## Verified vs not

- **Verified**: the adapter end-to-end — real TBA OAuth 1.0a signing (independently checked
  by the mock), SuiteTalk REST URL shapes, `204 + Location` create contract, externalId
  idempotency, SuiteQL reads, record transforms, cancel, and a rejected bad signature.
- **Not verified (honest gap)**: a live NetSuite sandbox. By design this is a `base_url` +
  secret change only; `docs/erps/netsuite/supply-chain-check.md` is the remaining real-world
  walk. NetSuite runs polling-only until the thin-webhook fast path is wired (out of scope,
  documented).

## Extensions applied
- Resiliency (enabled): per-call timeout + terminal/transient classification. Infra/DR
  rules N/A (no new infra).
- PBT (partial): `_map_netsuite` property test (never raises; unmapped → None).
- Security baseline (not enabled for this local/PoC increment, matching Increment 2): secret
  via Secrets Manager JSON, never logged; signing components never echoed.
