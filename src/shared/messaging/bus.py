"""In-memory message bus.

Models the production topology (Service Bus topic -> filtered subscriptions -> consumers,
with per-consumer dedup and redelivery to a dead-letter queue) without any cloud
dependency, so unit and integration tests are deterministic. Production swaps in the Azure
Service Bus adapter behind the same `EventPublisher` port + a `MessageConsumer` runner.

Simplifications vs the real broker (documented on purpose):
- Delivery is driven explicitly via `run_until_empty()` (no background threads) for
  deterministic tests.
- Ordering is preserved by enqueue order per subscription (good enough to model
  MessageGroupId ordering for single-threaded drains).
- Redrive: a message that keeps failing is dead-lettered after `max_receive` attempts.
- Dedup: consumers skip an `event_id` they have already processed (models both the
  publish-side MessageDeduplicationId and at-least-once redelivery).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from src.shared.eventsourcing import StoredEvent

MessageHandler = Callable[[StoredEvent], None]


@dataclass
class Subscription:
    """A consumer bound to the topic, optionally filtered by event type."""

    name: str
    handler: MessageHandler
    event_types: frozenset[str] | None = None  # None => receive all
    max_receive: int = 5

    def accepts(self, event: StoredEvent) -> bool:
        return self.event_types is None or event.event_type in self.event_types


@dataclass
class _ConsumerState:
    subscription: Subscription
    queue: list[StoredEvent] = field(default_factory=list)
    dead_letter: list[StoredEvent] = field(default_factory=list)
    processed: set[str] = field(default_factory=set)
    attempts: dict[str, int] = field(default_factory=dict)


class InMemoryMessageBus:
    """A synchronous topic+queues bus. Implements the `EventPublisher` port."""

    def __init__(self) -> None:
        self._consumers: list[_ConsumerState] = []

    # --- wiring ---
    def subscribe(
        self,
        name: str,
        handler: MessageHandler,
        *,
        event_types: frozenset[str] | set[str] | None = None,
        max_receive: int = 5,
    ) -> None:
        types = frozenset(event_types) if event_types is not None else None
        sub = Subscription(name=name, handler=handler, event_types=types, max_receive=max_receive)
        self._consumers.append(_ConsumerState(subscription=sub))

    # --- EventPublisher port ---
    def publish(self, events: list[StoredEvent]) -> None:
        """Fan out to every matching consumer queue (the topic + filter policies)."""
        for event in events:
            for consumer in self._consumers:
                if consumer.subscription.accepts(event):
                    consumer.queue.append(event)

    # --- delivery (explicit, for deterministic tests) ---
    def run_until_empty(self) -> None:
        """Drain every queue, applying retry-to-DLQ and per-consumer dedup."""
        while any(c.queue for c in self._consumers):
            for consumer in self._consumers:
                batch = consumer.queue[:]
                consumer.queue.clear()
                for event in batch:
                    self._deliver_one(consumer, event)

    def deliver(self, events: list[StoredEvent]) -> None:
        """Convenience: publish then drain."""
        self.publish(events)
        self.run_until_empty()

    def _deliver_one(self, consumer: _ConsumerState, event: StoredEvent) -> None:
        if event.event_id in consumer.processed:
            return  # idempotent: already handled by this consumer
        try:
            consumer.subscription.handler(event)
            consumer.processed.add(event.event_id)
        except Exception:
            attempts = consumer.attempts.get(event.event_id, 0) + 1
            consumer.attempts[event.event_id] = attempts
            if attempts >= consumer.subscription.max_receive:
                consumer.dead_letter.append(event)
            else:
                consumer.queue.append(event)

    # --- introspection (for tests / operator tooling) ---
    def dead_letters(self, consumer_name: str) -> list[StoredEvent]:
        return self._state(consumer_name).dead_letter

    def processed_count(self, consumer_name: str) -> int:
        return len(self._state(consumer_name).processed)

    def _state(self, consumer_name: str) -> _ConsumerState:
        for consumer in self._consumers:
            if consumer.subscription.name == consumer_name:
                return consumer
        raise KeyError(f"no consumer named '{consumer_name}'")
