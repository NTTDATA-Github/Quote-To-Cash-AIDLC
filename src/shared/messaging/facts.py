"""Fact publishing for plain-CRUD domains (catalog, connections, tenancy) — distinct from
event sourcing. Per ADR-0002, these domains' rows are the source of truth, not an event
log; nothing here replays or reconstructs state from facts. This exists so other domains
can react to a change (a connection paused, an item's price changed) without polling or a
direct synchronous call into these modules — reusing the exact same transport Order's own
events already use (outbox -> Service Bus topic -> subscriptions, or the in-memory bus
locally). No new infrastructure: `platform-domain-events` already carries every event type; a new
event type just means no queue's filter policy matches it yet, until one is added.

ponytail: `OutboxFactPublisher.publish` commits in its own transaction, separate from the
repository write that triggered it — not the same transaction as `PostgresEventStore`'s
event+outbox write. A crash in that split-second window drops the fact, not the data.
Acceptable today because nothing consumes these facts yet (zero observable impact);
upgrade to a shared-session write if a future consumer makes this load-bearing.
"""

from __future__ import annotations

from typing import Any, Protocol

from src.shared.eventsourcing.events import StoredEvent, new_id, utcnow


class FactPublisher(Protocol):
    def publish(self, fact: StoredEvent) -> None: ...


def make_fact(
    *,
    stream_id: str,
    aggregate_type: str,
    event_type: str,
    payload: dict[str, Any],
    tenant_id: str | None = None,
) -> StoredEvent:
    return StoredEvent(
        stream_id=stream_id,
        aggregate_type=aggregate_type,
        version=0,  # not sourced/replayed — version is meaningless for a plain-CRUD fact
        event_type=event_type,
        event_id=new_id(),
        occurred_at=utcnow(),
        payload=payload,
        tenant_id=tenant_id,
    )


class NullFactPublisher:
    """Discards facts. For tests that don't care about them."""

    def publish(self, fact: StoredEvent) -> None:
        return None


class CollectingFactPublisher:
    """Records everything published — for tests that assert on facts."""

    def __init__(self) -> None:
        self.published: list[StoredEvent] = []

    def publish(self, fact: StoredEvent) -> None:
        self.published.append(fact)


class BusFactPublisher:
    """Memory profile: publish straight onto the same `InMemoryMessageBus` Order uses."""

    def __init__(self, bus: Any) -> None:
        self._bus = bus

    def publish(self, fact: StoredEvent) -> None:
        self._bus.publish([fact])


class OutboxFactPublisher:
    """Postgres profile: write directly into `outbox` — the same table/relay/topic path
    `PostgresEventStore` uses for `Order`, just without a corresponding `events` row
    (there's nothing to replay for a plain-CRUD fact)."""

    def __init__(self, session_factory: Any) -> None:
        self._session_factory = session_factory

    def publish(self, fact: StoredEvent) -> None:
        from src.shared.persistence.tables import outbox_table

        session = self._session_factory()
        try:
            session.execute(
                outbox_table.insert().values(
                    event_id=fact.event_id,
                    event_type=fact.event_type,
                    stream_id=fact.stream_id,
                    aggregate_type=fact.aggregate_type,
                    tenant_id=fact.tenant_id,
                    correlation_id=fact.correlation_id,
                    payload=dict(fact.payload),
                    occurred_at=fact.occurred_at,
                )
            )
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()
