# Domain Entities — U4 Admin & Configuration

**Updated 2026-10-15** (supersedes the original MVP-era entities below the line). These are
the real backend domain objects the operator GraphQL schema wraps, not request/response
DTOs for a JSON API — the original model's framing (fixed DTOs around a config table) no
longer matches how this unit is actually built.

## `ErpConnection` (`src/modules/reference/connections/domain/models.py`)
- `connection_id`, `erp_type: str` (open, normalized uppercase+trim — ADR-0021, not the
  old closed enum), `instance_label`, `base_url`, `credentials: dict[str, str]` (generic,
  adapter-interpreted bag — ADR-0012), `secret_ref` (Secrets Manager pointer, `""` when
  `auth_type = NONE`), `status` (ACTIVE/PAUSED), `webhook_secret_ref` (separate from
  `secret_ref` — different credential, different purpose), `auth_type` (read only by the
  onboarding probe, ignored by a real adapter).
- `hasAdapter` is **not a field** — it's derived at read time from the adapter registry
  (`composition.py`'s `has_adapter`) and only appears on the GraphQL `ConnectionType`.

## `Reseller` (`src/modules/reference/tenancy/domain/models.py`)
- `tenant_id` (the stable, opaque partition key — unchanged meaning), `name` (new display
  field, purely cosmetic — see BR-U4-7).

## `TenantConnectionBinding` (unchanged)
- `binding_id`, `tenant_id`, `connection_id`, `erp_customer_id`, `status`
  (TO_VERIFY/VERIFIED/REMOVED).

## `MappingJob` (`src/modules/integration/mapping/domain/models.py`)
- `job_id`, `connection_id: str | None` (new — set for every job submitted through the
  current flow; `None` only for jobs that predate this field), `erp_name` (snapshotted
  from the connection's `instance_label` at submit time), `status`
  (PENDING/PROCESSING/DONE/FAILED), `canonical_fields_csv`, `sample_exports`,
  `schema_name`, `result: list[MappingEntry] | None`, `error`, `adapter_run_id`,
  `created_at`.

## `CanonicalSchema` (unchanged)
- `name`, `csv_text`, `created_at` — a reusable, named canonical-field list.

## `SampleRequestSpec` / `ProbeSample` (new — the live-probe mechanism)
- `SampleRequestSpec`: `label`, `method`, `path`, `query_params` — one HTTP call the probe
  makes against a connection's `base_url`.
- `ProbeSample`: `label`, `text | None`, `error | None` — exactly one of `text`/`error` is
  set; a failed request never sinks the others in the same probe call.

## `AuthConfig` / `AuthType` (`src/shared/erp_auth`, new)
- `AuthType`: `NONE | API_KEY_HEADER | BASIC | BEARER_TOKEN` — declarative only; nothing
  needing a handshake (OAuth1 signing) or a human redirect (OAuth2 authorization-code) is
  modeled here (see ADR-0021's alternatives-considered).
- `AuthConfig`: `auth_type`, `params: dict[str, str]` (non-secret — e.g. a header name) —
  the one secret is always resolved separately via `SecretStore`, never put in `params`.

## GraphQL-layer types (`src/api/graphql/operator/types.py`)
- `ConnectionType` — `ErpConnection` + derived `hasAdapter: bool`.
- `ResellerType`, `MappingJobType`, `ProbeSampleType`, `AuthConfigInput`,
  `SampleRequestInput` — thin wrappers, no logic of their own.

---

## Superseded (original MVP-era entities, kept for history — do not build against this)

U4 reuses the U0 config domain (ErpInstance, RoutingRule/RoutingCondition, MappingDefinition/MappingEntry) and their tables. It defines admin API DTOs.

### Request DTOs
- `RegisterInstanceRequest` — { erp_type, display_name, connection_ref }
- `RoutingRuleRequest` — { order_index, conditions[], target_instance_id, enabled }
- `ReorderRequest` — { ordered_rule_ids[] }
- `MappingRequest` — { instance_id, data_type, direction, field_entries[] }

### Response DTOs
- `InstanceView`, `RoutingRuleView`, `MappingView`
- `ConfigView` — { instances[], routing_rules[], mappings[] }
- `MappingReport` — { unmapped_required[], warnings[] }
- `ConnectivityResult` — { instance_id, reachable }

None of `ErpInstance`, `RoutingRule`, `RoutingCondition`, or the old `MappingDefinition`/
`MappingEntry` (field-entries table) exist in the real codebase — the real `MappingEntry`
(above) is an LLM-proposed field pairing, not an admin-authored one, and is a different
shape entirely.
