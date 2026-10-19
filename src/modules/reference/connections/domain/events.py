"""Fact event types this domain publishes (see `src/shared/messaging/facts.py`).
`connections` is plain CRUD (ADR-0002) — these are notifications, not a replayable log."""

from __future__ import annotations

CONNECTION_REGISTERED = "ConnectionRegistered"
CONNECTION_PAUSED = "ConnectionPaused"
CONNECTION_RESUMED = "ConnectionResumed"
CONNECTION_RENAMED = "ConnectionRenamed"
