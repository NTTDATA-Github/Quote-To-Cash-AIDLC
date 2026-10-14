# Adding a new ERP

The platform currently has two registered ERPs: **Odoo** and **JSONPlaceholder Demo
ERP** (see `docs/erps/README.md` for both). This is the checklist for adding another one
(ERPNext, SAP, NetSuite, …) — four files, no scattered edits.

## The four touch points

1. **Status mapping** — `src/modules/integration/erp/domain/status_mapping.py`. Write one
   pure function `(fields: dict[str, str]) -> CanonicalStatus | None` reading whatever
   keys *this* ERP's status actually arrives in (inputs already lowercased/stripped) and
   add one line to `STATUS_MAPPERS`. The signature is a field bag, not a fixed arity —
   ERPNext reports status as a single combined string, so its mapper reads one key, where
   Odoo's reads two (`state` + `invoice_status`):
   ```python
   def _map_erpnext(fields: dict[str, str]) -> CanonicalStatus | None:
       return {
           "to deliver and bill": CanonicalStatus.CONFIRMED,
           "completed": CanonicalStatus.FULFILLED,
           "closed": CanonicalStatus.CLOSED,
           "cancelled": CanonicalStatus.CANCELLED,
       }.get(fields.get("status", ""))

   STATUS_MAPPERS: dict[str, StatusMapper] = {
       "ODOO": _map_odoo,
       "ERP_NEXT": _map_erpnext,  # <- add
   }
   ```

2. **Adapter** — new `src/modules/integration/erp/infrastructure/<erp>_adapter.py`
   implementing the `ErpAdapter` protocol (`submit` / `fetch_status` / `fetch_shipments` /
   `fetch_invoices` / `cancel`) from `integration/application/ports.py`. `fetch_status`
   returns `dict[str, str] | None` —
   the same field bag the status mapper reads, so return whatever fields your status
   mapper needs (Odoo's returns `{"state": ..., "invoice_status": ...}`). Follow
   `odoo_adapter.py`'s shape: stdlib-only HTTP (no new dependency for a simple REST/RPC
   client), explicit timeouts, and classify every failure as `terminal=True` (don't retry
   — e.g. validation errors, 4xx) or `terminal=False` (do retry — timeouts, 5xx,
   connection errors). Keep any pure payload-building logic (like
   `build_sale_order_lines`) as a free function so it's unit-testable without a live
   server — see `test_odoo_adapter.py` for the pattern (mock `_authenticate`/`_execute`,
   not a live Odoo). Two things worth copying from Odoo's adapter, not reinventing per
   ERP: an idempotency check before creating anything (search for an existing record by
   your own reference first), and failing closed on an unresolvable reference (don't
   silently auto-create a phantom record in the ERP for a typo'd SKU/ID).
   `fetch_shipments` and `fetch_invoices` return the ERP's own done deliveries and posted
   customer invoices for one order. Return `[]` when that ERP has no such documents — the
   sweeper records whatever comes back, once per ERP id, and skips a SKU that is not on
   the order.

3. **Registration** — one line in `src/modules/integration/erp/infrastructure/registry.py`'s
   `build_adapter_registry`:
   ```python
   return {
       "ODOO": OdooAdapter(timeout_seconds=settings.erp_odoo_timeout_seconds),
       "ERP_NEXT": ErpNextAdapter(timeout_seconds=settings.erp_erpnext_timeout_seconds),  # <- add
   }
   ```
   (Add `erp_erpnext_timeout_seconds` to `Settings`/`get_settings()` if the new adapter
   needs its own timeout — don't reuse Odoo's.)

4. **The type itself** — one line in `ErpType`
   (`src/modules/reference/connections/domain/models.py`):
   ```python
   class ErpType(str, Enum):
       ODOO = "ODOO"
       ERP_NEXT = "ERP_NEXT"  # <- add
   ```

That's it — `composition.py`, `DeliveryHandler`, `ReconcileSweeper`, and the webhook
ingress route never change. They all dispatch on `erp_type: str` through the two
registries above, not through per-ERP conditionals.

## What you get for free

- **Multiple ERPs coexist.** Each `ErpConnection.erp_type` picks its own adapter and
  status mapper independently; nothing is a global "which ERP" switch.
- **Unregistered types fail safely, not silently and not by crashing.**
  `map_native_status` returns `None` (no transition) for an unmapped type —
  `test_unregistered_erp_type_is_none_never_raises` locks this in. The adapter registry
  is stricter on purpose: resolving an unregistered `erp_type` raises `UnknownErpType`
  (`integration/application/ports.py`), because *not delivering an order* is a real
  problem that belongs in DLQ triage, not a status update you can just skip.
- **`ERP_ADAPTER_MODE=stub` overrides everything**, regardless of how many ERPs are
  registered — useful for local dev/tests without any real ERP reachable (see
  `_resolve_adapter_for` in `composition.py`).

## Inbound webhooks are a separate, optional step

Adding an ERP to the registry makes outbound delivery + the reconciliation sweeper (item
C) work for it immediately. If it should also *push* status changes to us, that's
`docs/erps/<erp>/webhook.md`'s territory — either the HMAC route (if the ERP can sign
requests) or a shared-secret-in-path route like Odoo's (if it can't). Neither is
required: every registered ERP gets reconciliation polling regardless.

## Why ERPNext isn't registered right now

It was removed as part of a refactor from ad hoc if/elif dispatch (scattered across
`status_mapping.py` and `composition.py`) to the registry pattern above — partly because
`ErpType.ERP_NEXT` existed with a status mapper but no adapter ever implemented, and
partly to prove out this checklist with a clean example before other developers or
automation rely on it. Adding it back is exactly the 4-step process described here.

## Read next
- **`docs/erp-integration-patterns.md`** — webhook shapes (rich vs. thin/NetSuite-style)
  and how multiple instances of an ERP, and multiple tenants, get routed without
  tangling. Read this before writing a new adapter for an ERP with unusual webhooks.
- **`docs/erps/`** — one folder per ERP (`README.md`, `webhook.md`, `supply-chain-check.md`).
  Copy `docs/erps/_template/` once the adapter is registered.
- **`aidlc-docs/inception/application-design/target-architecture.md`** / **`docs/database-schema.md`**
  — the system this adapter plugs into.
