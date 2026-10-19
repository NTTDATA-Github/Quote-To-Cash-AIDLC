"""Messaging: the event-distribution seam.

`EventPublisher` (the port the repository/relay call) is re-exported from the kernel.
`InMemoryMessageBus` is the local/test implementation modeling topic -> queues -> DLQ.
Production adds the Azure Service Bus adapter (azure-servicebus)
implementing the same port + a consumer runner — see application-design/messaging-topology.md.
"""

from __future__ import annotations

from src.shared.eventsourcing import EventPublisher

from .bus import InMemoryMessageBus, MessageHandler, Subscription

__all__ = [
    "EventPublisher",
    "InMemoryMessageBus",
    "MessageHandler",
    "Subscription",
]
