"""Event publisher port + simple in-memory implementations.

The port is what the repository calls after persisting events. Production binds an
Service Bus adapter (see shared/messaging); tests/local use the collecting/null ones here.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from .events import StoredEvent


@runtime_checkable
class EventPublisher(Protocol):
    def publish(self, events: list[StoredEvent]) -> None: ...


class NullEventPublisher:
    """Discards events. Useful when the outbox is the only propagation path."""

    def publish(self, events: list[StoredEvent]) -> None:
        return None


class CollectingPublisher:
    """Records everything published — for tests and local inspection."""

    def __init__(self) -> None:
        self.published: list[StoredEvent] = []

    def publish(self, events: list[StoredEvent]) -> None:
        self.published.extend(events)
