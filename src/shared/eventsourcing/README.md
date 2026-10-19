# `shared/eventsourcing` — a small event-sourcing kernel, taught from real code

This is a **dependency-free** core (no boto3, no SQLAlchemy, no web framework) that any
domain module can build an event-sourced aggregate on top of. This page teaches the
concepts one at a time, using the platform's real `Order` aggregate
(`src/modules/ordering/domain/`) as the example throughout — not a toy, the actual
production code. For *why* this project uses event sourcing at all (the business
reasons), see `docs/event-sourcing-explained.md`; this page is the *how*.

If you've never worked with event sourcing before, read this top to bottom once. It's
short on purpose.

## The one-sentence idea

Instead of storing "what is true right now" (a row you overwrite), you store "everything
that happened" (a list of facts you only ever add to) — and *compute* "what is true right
now" by replaying that list.

## The six pieces, in the order you'll use them

### 1. `DomainEvent` — a fact that happened

An immutable record of something that occurred. Frozen (can't be mutated after creation),
keyword-only (no positional-argument bugs), and registered so the kernel can rebuild it
from storage later.

```python
# src/modules/ordering/domain/events.py
@register_event
@dataclass(frozen=True, kw_only=True)
class OrderSubmitted(DomainEvent):
    order_id: str
    tenant_id: str
    client_reference: str
    lines: list[dict[str, Any]]
    product_keys: list[str]
```

`event_id` and `occurred_at` come free from the `DomainEvent` base — every event has them
without declaring them.

**Rule of thumb:** name events in the past tense (`OrderSubmitted`, not `SubmitOrder`) —
an event is a record that something *already happened*, never an instruction to do
something.

### 2. `Aggregate` — an object whose entire life is a sequence of events

The `Order` class extends `Aggregate`. Two things make it one:

- **Commands** are ordinary methods that check invariants and, if the change is allowed,
  call `self.emit(...)` — they never mutate `self` directly.
- **Applies** (`_apply_<EventName>`) are the *only* place state actually changes. They run
  both the moment an event is emitted *and* every time the aggregate is rebuilt by replay
  — so they must be pure, deterministic functions of `(current state, event) -> new state`.

```python
# src/modules/ordering/domain/aggregate.py
class Order(Aggregate):
    aggregate_type = "Order"

    def confirm(self) -> None:                     # command: behavior + invariant
        if self.state is OrderState.CONFIRMED:
            return                                  # idempotent — already there
        self._require(OrderState.SENT_TO_ERP, "confirm")   # invariant: guard the transition
        self.emit(OrderConfirmed(order_id=self.id))         # record the fact

    def _apply_OrderConfirmed(self, e: OrderConfirmed) -> None:   # apply: the ONLY state change
        self.state = OrderState.CONFIRMED
```

Notice `confirm()` doesn't set `self.state` itself — `emit()` calls `apply()` internally,
which finds `_apply_OrderConfirmed` by naming convention and runs it. This split
(command decides *whether*, apply decides *what changes*) is the whole discipline of
event sourcing in one method pair.

**Why this matters:** because `_apply_*` methods are the only mutation path, replaying
every event from the beginning always reconstructs the exact same state — there's no
other code path that could have snuck in a change.

### 3. `EventStore` — appends facts, never updates them

```python
class EventStore(Protocol):
    def append(self, stream_id: str, expected_version: int, events: list[StoredEvent]) -> None: ...
    def load(self, stream_id: str, after_version: int = 0) -> list[StoredEvent]: ...
```

One "stream" per aggregate instance (`stream_id` = the order's id). `append` takes the
version you *expect* the stream to be at — this is **optimistic concurrency control**: if
someone else appended in between your read and your write, the actual version has moved
and you get a `ConcurrencyError` instead of silently clobbering their change.

```python
store = InMemoryEventStore()
store.append("ord_1", 0, [event_a])       # ord_1 is now at version 1
store.append("ord_1", 0, [event_b])       # ConcurrencyError: expected 0, found 1
store.append("ord_1", 1, [event_b])       # correct — now at version 2
```

`InMemoryEventStore` (in this kernel) is for tests and simple local runs.
`PostgresEventStore` (`src/shared/persistence/event_store.py`) implements the identical
protocol against a real table — nothing above it changes.

### 4. `EventSourcedRepository` — replay to read, append to write

This is the class most code actually touches. It hides steps 2 and 3 behind two methods:

```python
repo = EventSourcedRepository(InMemoryEventStore(), Order)

order = Order.submit(order_id="ord_1", tenant_id=TenantId("tnt_1"),
                      client_reference="PO-1", lines=[...])
repo.save(order)                 # collects order's pending events, appends them

same_order = repo.get("ord_1")   # loads every event for "ord_1", replays them one by one
same_order.confirm()             # a normal command call — emits OrderConfirmed
repo.save(same_order)            # appends just the NEW event (version-checked)
```

`get()` never "loads a row" — it constructs a blank `Order`, then calls `apply()` once per
stored event, in order. Whatever state `Order` ends up in after that loop *is* its current
state, full stop. There is no other place "the current status" lives.

### 5. `Outbox` + `EventPublisher` — how events leave this process

`save()` optionally does two more things after appending, if you wired them in:

- **Outbox**: writes the same events to an outbox table, in the *same transaction* as the
  append (no dual-write race). A separate relay process reads the outbox later and
  publishes to the real message bus. See `docs/database-schema.md`'s outbox section.
- **Publisher**: publishes events directly (used by the in-memory/test setup, where there's
  no separate relay process to wait for).

Both are ports; production binds an Azure Service Bus publisher and a Postgres-backed outbox
(`src/shared/messaging/`, `src/shared/persistence/`) — the aggregate and repository never
know which.

### 6. `Snapshot` — bounding replay cost for long-lived aggregates

Replaying 3 events is instant. Replaying 30,000 is not. A snapshot is a checkpoint: "at
version 500, the state looked like *this*" — so `get()` loads the snapshot, then only
replays events *after* it, instead of from event 1.

```python
class Order(Aggregate):
    def snapshot_state(self) -> dict[str, Any]:
        return {"tenant_id": str(self.tenant_id), "state": self.state.value, ...}

    def restore(self, state: dict[str, Any]) -> None:
        self.tenant_id = TenantId(state["tenant_id"])
        self.state = OrderState(state["state"])
        ...
```

Pass `snapshot_every=N` to `EventSourcedRepository` to take one automatically every N
versions. `Order`'s lifecycle is short (under a dozen events, typically), so this is
defined but not aggressively tuned here — it matters far more for aggregates with
thousands of events.

## Tracing one real order end to end — actual rows, not a hypothetical

Everything above is easier to trust once you've seen it happen. Below are the **actual
rows** for a real order (`ord_625ecc621614`) that ran through this system's local dev
environment, pulled straight out of the `events` table with `SELECT * FROM events WHERE
stream_id = 'ord_625ecc621614' ORDER BY version`. Nothing here is simplified or invented.

| v | event_type | occurred_at | payload |
|---|---|---|---|
| 1 | `OrderSubmitted` | 15:52:08.369 | `{"order_id": "ord_625ecc621614", "tenant_id": "tnt_demo", "client_reference": "WEBHOOK-TEST-3", "lines": [{"product_key": "ANVIL", "quantity": 1.0, "unit_of_measure": "EA"}], "product_keys": ["ANVIL"]}` |
| 2 | `OrderValidated` | 15:52:09.148 | `{"order_id": "ord_625ecc621614", "owning_connection_id": "conn_odoo_local"}` |
| 3 | `OrderReadyForDelivery` | 15:52:09.148 | `{"order_id": "ord_625ecc621614", "owning_connection_id": "conn_odoo_local"}` |
| 4 | `OrderSentToErp` | 15:52:10.256 | `{"order_id": "ord_625ecc621614", "erp_order_id": "SO_a5150b6dbe21"}` |
| 5 | `OrderConfirmed` | 16:06:59.980 | `{"order_id": "ord_625ecc621614"}` |

(every row also carries `stream_id: "ord_625ecc621614"`, `aggregate_type: "Order"`,
a unique `event_id`, and `tenant_id: "tnt_demo"` — omitted from the table above for width,
shown in full for row 1 below exactly as the database returned it)

```json
{
  "stream_id": "ord_625ecc621614",
  "aggregate_type": "Order",
  "version": 1,
  "event_type": "OrderSubmitted",
  "event_id": "c1df3120a72c4628a12f4b6110e861af",
  "occurred_at": "2026-09-27T15:52:08.369940+00:00",
  "tenant_id": "tnt_demo",
  "correlation_id": null,
  "payload": { "order_id": "ord_625ecc621614", "tenant_id": "tnt_demo", "client_reference": "WEBHOOK-TEST-3", "lines": [{"product_key": "ANVIL", "quantity": 1.0, "unit_of_measure": "EA"}], "product_keys": ["ANVIL"] }
}
```

**Notice what's *not* in this table**: no `status` column, no `client_reference` column
after row 1, no "current state" anywhere. Five facts, appended once each, never updated.

### What replaying these five rows actually produces

`repo.get("ord_625ecc621614")` builds a blank `Order`, then calls `_apply_OrderSubmitted`,
`_apply_OrderValidated`, `_apply_OrderReadyForDelivery`, `_apply_OrderSentToErp`,
`_apply_OrderConfirmed` — in that order, each one a small, deterministic mutation. What
comes out the other end, as real field values on the in-memory object:

```
Order(
  id="ord_625ecc621614", tenant_id="tnt_demo", client_reference="WEBHOOK-TEST-3",
  lines=[OrderLine(product_key="ANVIL", quantity=1.0, unit_of_measure="EA")],
  state=OrderState.CONFIRMED, owning_connection_id="conn_odoo_local",
  erp_order_id="SO_a5150b6dbe21", retry_attempt=0, version=5,
)
```

Every one of those values is traceable back to exactly one row above — `state=CONFIRMED`
came *only* from row 5 existing; if it hadn't been appended yet, replay would stop at row
4 and `state` would be `SENT_TO_ERP` instead. That's the entire mechanism.

### The other real row this produces: the read-side projection

The `orders` table (a different table — the CQRS read side, see
`docs/event-sourcing-explained.md`) has its own row for the same order, kept in sync by a
projector listening for these exact events. Also a real row, same order:

```json
{
  "order_id": "ord_625ecc621614", "tenant_id": "tnt_demo", "client_reference": "WEBHOOK-TEST-3",
  "state": "CONFIRMED", "owning_connection_id": "conn_odoo_local", "erp_order_id": "SO_a5150b6dbe21",
  "lines": [{"product_key": "ANVIL", "quantity": 1.0, "unit_of_measure": "EA"}]
}
```

Same `state: CONFIRMED`, computed two different ways: the aggregate gets there by
*replaying every event on demand*; the projection gets there by *updating one row every
time a new event arrives*. Both are "correct" — the aggregate is truth, the projection is
a fast, disposable cache of it that could be dropped and rebuilt from the events table at
any time without losing anything.

## A minimal template (copy this to start a new aggregate)

Everything above, stripped to its smallest possible working shape:

```python
@register_event
@dataclass(frozen=True, kw_only=True)
class Incremented(DomainEvent):
    by: int

class Counter(Aggregate):
    aggregate_type = "Counter"

    def __init__(self, id: str) -> None:
        super().__init__(id)
        self.total = 0

    def increment(self, by: int) -> None:
        if by <= 0:
            raise ValueError("by must be positive")
        self.emit(Incremented(by=by))

    def _apply_Incremented(self, e: Incremented) -> None:
        self.total += e.by

repo = EventSourcedRepository(InMemoryEventStore(), Counter)
c = Counter("counter-1")
c.increment(5)
repo.save(c)
same = repo.get("counter-1")   # total == 5, rebuilt entirely from events
```

## Rules that keep this clean (and the anti-patterns they avoid)

- **Behavior lives in the aggregate, not in services.** Services orchestrate (call
  `repo.get`, call a command, call `repo.save`); the aggregate decides and `emit`s.
  Avoids the *anemic domain model* anti-pattern, where "objects" are just data bags and
  all the logic lives in service functions instead.
- **Only event-source aggregates that need it.** `Order` uses this kernel because its
  lifecycle and history genuinely matter. `erp_connections`, `items`,
  `tenant_connection_bindings` are plain rows, updated in place — they have no
  interesting state machine worth replaying. Event-sourcing everything indiscriminately is
  ceremony, not a virtue.
- **No domain types in the kernel.** This file has never heard of `Order`, `Tenant`, or
  `ErpConnection`, and never will — that's what keeps it reusable and stable. Avoids a
  shared kernel slowly turning into a dumping ground.
- **The store is the only persistence seam.** Swap `InMemoryEventStore` for
  `PostgresEventStore` behind the same `EventStore` protocol; nothing in `Order` or
  `EventSourcedRepository` changes. Avoids vendor/infrastructure lock-in leaking into
  domain code.
- **This kernel is thin on purpose.** It doesn't wrap a heavyweight event-sourcing
  framework — so we're not double-abstracting someone else's abstraction.

## Where to look next

- `docs/event-sourcing-explained.md` — the *why* (concrete reasons this project needed
  it, and the CQRS/projection split that keeps reads fast).
- `docs/database-schema.md` — what the `events`/`outbox`/`snapshots` tables actually look
  like once `PostgresEventStore` is in the picture.
- `src/modules/ordering/domain/aggregate.py` + `events.py` — the real thing, in full.
- `src/shared/eventsourcing/tests/test_kernel.py` — the kernel's own tests, using the
  `Counter` example above; good next read if you want to see every edge case
  (concurrency conflicts, snapshots, unknown event types) exercised directly.
