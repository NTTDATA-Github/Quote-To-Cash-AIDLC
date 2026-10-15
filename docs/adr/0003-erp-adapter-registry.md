# ADR-0003: ERPs plug in via an adapter + registry pattern

| | |
|---|---|
| Status | Accepted — **amended by [ADR-0021](0021-connections-before-adapters.md)** |
| Affects | `integration` module |

> **Amendment (ADR-0021):** touch point 4 below (`ErpType` enum member) no longer
> exists — `ErpConnection.erp_type` is a plain, normalized string now, so a connection
> (and a mapping proposal for it) can exist before an adapter does. Adding a new ERP is
> 3 touch points today, not 4.

## In one sentence
Every ERP implements one protocol and one status-mapping function; adding a new ERP is
exactly 4 file touches, never a change to shared dispatch logic.

## Why this needed a decision

| Problem | Detail |
|---|---|
| Multiple ERP kinds, one codebase | Odoo today, NetSuite/SAP later — no other module should need to know which ERP it's dealing with |

## The decision
Every ERP implements `ErpAdapter` (`submit` / `fetch_status` / `cancel`) and one pure
status-mapping function `(fields: dict[str, str]) -> CanonicalStatus | None` — a field
bag, not a fixed arity, so a 1-field ERP (a single combined status string) and a 3-field
one both fit the same signature without forcing Odoo's particular 2-field shape onto
anyone else. Adding an ERP touches exactly these 4 places, nothing else:

| # | Touch point | File |
|---|---|---|
| 1 | Status mapper (one pure function + one registry line) | `integration/domain/status_mapping.py` |
| 2 | Adapter implementing `ErpAdapter` | `integration/infrastructure/<erp>_adapter.py` |
| 3 | Registry entry | `integration/infrastructure/registry.py` |
| 4 | Enum member | `connections/domain/models.py` (`ErpType`) |

`composition.py`, `DeliveryHandler`, `ReconcileSweeper`, and the webhook ingress route all
dispatch on `erp_type: str` through the two registries above — none of them change per-ERP.

## Alternatives considered

| Option | Rejected because |
|---|---|
| `if/elif` dispatch on ERP type scattered across the codebase | This is literally what the current pattern replaced — ERPNext existed with a status mapper but no adapter, because the old approach let per-ERP logic drift out of sync |
| A declarative mapping engine / `mapping_definitions` table | More upfront machinery than the current per-ERP volume justifies; each adapter's field-mapping in code is simple enough today |

## Consequences

| | |
|---|---|
| ✅ | Multiple ERPs coexist; each `ErpConnection.erp_type` picks its adapter and status mapper independently |
| ✅ | Unregistered types fail safely: status mapping returns "no transition," but resolving an adapter raises `UnknownErpType` — silently failing to deliver an order is a real problem, not something to shrug off |
| ⚠️ | The pattern only covers order-fulfillment-shaped backends (submit/status/cancel). CRM systems (Salesforce, HubSpot) and carrier tracking (AfterShip) are a different shape and need their own adapter family, not a forced fit into `ErpAdapter` |

## Revisit when
A new integration category (CRM, carrier tracking) is added — it needs its own protocol,
not an extension of `ErpAdapter`.
