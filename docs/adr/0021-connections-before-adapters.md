# ADR-0021: ERP connections can exist before an adapter does

| | |
|---|---|
| Status | Accepted |
| Affects | `connections` module, `integration` module, operator GraphQL/UI |

## In one sentence
A connection row (base URL + auth + secret) can be created for any ERP — known or brand
new — the moment someone knows how to reach it; whether code exists to actually deliver
orders through it (`hasAdapter`) is a separate, later, derived fact, never a precondition
for creating the row.

## Why this needed a decision

| Problem | Detail |
|---|---|
| "I have a connection" and "onboarding a new ERP" were two disconnected concepts | `ErpType` was a closed enum (ADR-0003's step 4 of "add a new ERP"): `registerConnection` rejected any `erp_type` without a prior, manual enum-member addition — so a connection literally could not exist for an ERP until *after* its adapter shipped. |
| The mapping-proposer UI worked around this by never touching `erp_connections` at all | It collected base URL/credentials inline, on its own page, for a one-off probe — a second, throwaway, disconnected place credentials for the same real-world ERP instance lived, never reused if that instance needed pausing, re-authing, or a second instance later. |
| Operators think "add the ERP, then map its fields" — not the reverse | The product flow this ADR enables (connections-first, mapping reads an existing connection) matches how every comparable integrations UI (Stripe, Zapier, Retool) is actually used. |

## The decision
- `ErpConnection.erp_type` is a plain, normalized string (uppercase + trimmed) — not
  validated against a closed `ErpType` enum at the API boundary. Already a `TEXT` column
  since migration `0001`; no database migration is needed, only dropping the Python-side
  `ErpType(erp_type)` conversion in `register_connection`.
- Registering a connection never requires an adapter to already exist.
  `registerConnection` is now the *one* place every ERP instance is created — a known
  type or a brand-new one, no distinction in the API.
- "Does this ERP type have a working adapter" (`hasAdapter`) is derived on read from
  `build_adapter_registry` (ADR-0003's registry) — never stored. A connection whose type
  isn't in the registry behaves exactly as ADR-0003 already specified for an unknown
  type: delivery raises `UnknownErpType`, a visible configuration gap, never silent data
  loss.
- Probing such a connection for mapping-proposal sample data (no adapter exists yet, so
  there's no `submit`/`fetch_status` to call) goes through a small, declarative
  auth-strategy registry (`src/shared/erp_auth`): `NONE` / `API_KEY_HEADER` / `BASIC` /
  `BEARER_TOKEN` today. Each strategy turns one resolved secret into headers/params for a
  single request; nothing needing a handshake (OAuth1 per-request signing) or a human
  consent redirect (OAuth2 authorization-code) is built yet — the same "declare the
  common case now, add the exotic one when a real ERP demands it" reasoning ADR-0015
  already used for `ErpCapabilities`.
- Every outbound URL this probe dials is validated against private/loopback/link-local/
  metadata-endpoint ranges first (`src/shared/net/ssrf_guard.py`) — the URL is
  operator-typed input being dialed on the strength of nobody's review yet, a materially
  different trust level than a connection's already-vetted `base_url` on the live
  delivery path.

## Alternatives considered

| Option | Rejected because |
|---|---|
| Keep `ErpType` as a closed enum; add a separate "pending ERP" table for not-yet-adapted connections | Two parallel places a connection can live, each with its own CRUD, its own UI, and its own migration path into the real table once an adapter ships — exactly the duplicated, divergent-over-time structure ADR-0012 already rejected for credentials |
| Let the mapping page keep collecting its own base URL/credentials inline, never touching `erp_connections` | The status quo this ADR replaces. It works, but means a second, disconnected way to "know about" an ERP instance exists, with credentials that are never reused |
| Build a full generic auth/handshake engine (OAuth1 signing, OAuth2 authorization-code with a redirect UI, SOAP WS-Security) up front, so probing "supports every ERP" | No second, real, exotic-auth ERP exists yet to prove the shape — manual sample-file upload stays the universal fallback regardless of auth type, so no ERP is ever blocked from onboarding; only the *live-probe convenience* is narrower today |

## Consequences

| | |
|---|---|
| ✅ | A connection is a single row from the moment it's known — known ERP or brand new — with one CRUD surface, one credentials model (ADR-0012), one place operators look |
| ✅ | Adding the *n*-th instance of an already-adapted ERP type is still a pure data change (ADR-0006, unchanged) — this ADR only changes what's true for the *first* instance of a brand-new type |
| ✅ | Dropping the `ErpType` enum check removes one of ADR-0003's four "add a new ERP" touch points — the enum member — so onboarding a brand-new ERP now needs no enum change anywhere |
| ⚠️ | Free-text `erp_type` reintroduces the typo risk the enum existed to prevent ("Shopify" vs "shopify" vs "ShopifyPOS" for the same real system). Mitigated by normalizing on write and by the Connections UI defaulting to "pick an already-used type" over a blank text field — not eliminated at the database level |
| ⚠️ | `hasAdapter` is a property of the *running process's deployed code*, not the database — staging and production can legitimately disagree if their adapter registries differ. Accepted: this already matches how `UnknownErpType` dispatch has always worked (ADR-0003) |

## Revisit when
An ERP's reachability can't be described by a base URL plus one resolved secret at all
(mutual TLS client certs, a vendor SDK managing its own connection pooling) — the real
adapter already has this freedom per ADR-0012; only the *probe* would need a structural
change beyond one more `AuthType`.
