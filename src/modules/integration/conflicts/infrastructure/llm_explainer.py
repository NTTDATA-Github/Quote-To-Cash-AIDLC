"""AI summaries of order conflicts, from an LLM client, or "unavailable" when none is set up.

The model is given the conflict's facts and nothing else: no customer records, no secrets, no
ERP payloads. Answers are cached per rendered fact set, so reopening a conflict with nothing
changed does not call the model again.
"""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING

from ..domain.models import ConflictExplanationUnavailable

if TYPE_CHECKING:
    from collections.abc import Callable

    from src.shared.llm.client import LlmClient

    from ..domain.models import OrderConflict

SYSTEM_PROMPT = (
    "You help an operator at a distributor understand why an order could not be delivered to "
    "its ERP. Use only the facts you are given. Reply in plain English in at most four short "
    "sentences: what happened, the most likely cause, and what the operator should check. Do "
    "not invent names, numbers or causes that are not in the facts. Do not suggest changing the "
    "order automatically."
)


def _facts(conflict: OrderConflict, reseller_name: str) -> str:
    return "\n".join(
        [
            f"Order: {conflict.order_id}",
            f"Reseller: {reseller_name}",
            f"What happened: {conflict.reason}",
            f"Reason code: {conflict.reason_code}",
            "Severity: "
            + (
                "the ERP rejected the order"
                if conflict.severity.value == "HIGH"
                else "delivery is still being retried"
            ),
            f"Delivery attempts so far: {conflict.attempts}",
            f"Opened: {conflict.opened_at.isoformat()}",
            f"Deadline: {conflict.sla_due_at.isoformat()}",
        ]
    )


class LlmConflictExplainer:
    def __init__(self, client_factory: Callable[[], LlmClient]) -> None:
        # Built on first use, so a missing key only affects the summary, never startup.
        self._client_factory = client_factory
        self._client: LlmClient | None = None
        self._cache: dict[str, str] = {}

    def explain(self, conflict: OrderConflict, reseller_name: str) -> str:
        # Keyed on the rendered facts themselves, not a hand-picked tuple of fields - a
        # tuple of (conflict_id, attempts, reason) missed a changed reseller name or
        # severity, silently serving a summary that no longer matched what's shown.
        facts = _facts(conflict, reseller_name)
        key = hashlib.sha256(facts.encode()).hexdigest()
        if key not in self._cache:
            if self._client is None:
                self._client = self._client_factory()
            self._cache[key] = self._client.ask(SYSTEM_PROMPT, facts).strip()
        return self._cache[key]


class UnavailableConflictExplainer:
    def explain(self, conflict: OrderConflict, reseller_name: str) -> str:
        raise ConflictExplanationUnavailable(
            "No AI provider is set up for this environment, so no summary is available. "
            "Set LLM_PROVIDER to enable summaries."
        )
