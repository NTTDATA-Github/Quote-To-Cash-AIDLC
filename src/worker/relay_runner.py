"""Runs the outbox relay in a loop (Postgres outbox -> Service Bus)."""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.shared.persistence.relay import OutboxRelay

log = logging.getLogger(__name__)


class RelayRunner:
    def __init__(self, relay: OutboxRelay, idle_sleep_seconds: float = 1.0) -> None:
        self._relay = relay
        self._idle_sleep = idle_sleep_seconds

    def run_forever(self) -> None:  # pragma: no cover - long-running loop
        while True:
            try:
                published = self._relay.run_once()
            except Exception:
                # stop the relay; the unpublished outbox rows are still there next pass.
                log.exception("outbox relay pass failed; retrying after idle_sleep")
                time.sleep(self._idle_sleep)
                continue
            if published == 0:
                time.sleep(self._idle_sleep)
