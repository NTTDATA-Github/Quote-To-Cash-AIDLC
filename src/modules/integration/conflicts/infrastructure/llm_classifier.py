"""Suggests a cause for an ERP message that no rule recognised.

Only messages the rules put in OTHER are sent here. The model is given the message and the list
of causes, and must answer with one cause id. Anything else is discarded, and the conflict stays
OTHER. Answers are cached per message, so each distinct message is asked once.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from src.shared.llm.client import retry_with_backoff

from ..domain.categories import LABELS, ConflictCategory

if TYPE_CHECKING:
    from collections.abc import Callable

    from src.shared.llm.client import LlmClient

SYSTEM_PROMPT = (
    "You classify an error message that an ERP returned when it refused an order. Choose exactly "
    "one cause from this list and answer with its id only, nothing else:\n"
    + "\n".join(
        f"{c.value}: {LABELS[c]}" for c in ConflictCategory if c is not ConflictCategory.OTHER
    )
    + "\nOTHER: none of the above."
)


def _parse(answer: str) -> ConflictCategory | None:
    token = answer.strip().strip(".").upper()
    try:
        return ConflictCategory(token)
    except ValueError:
        return None


class LlmCauseClassifier:
    def __init__(self, client_factory: Callable[[], LlmClient]) -> None:
        self._client_factory = client_factory
        self._client: LlmClient | None = None
        self._cache: dict[str, ConflictCategory | None] = {}

    def classify(self, message: str) -> ConflictCategory | None:
        """The suggested cause, or None when the model fails (after retrying) or gives an
        answer we don't know."""
        if message not in self._cache:
            try:
                if self._client is None:
                    self._client = self._client_factory()
                client = self._client
                answer = retry_with_backoff(lambda: client.ask(SYSTEM_PROMPT, message))
                self._cache[message] = _parse(answer)
            except Exception:
                # A failed call (even after retries) is not cached, so the next
                # delivery failure for this order tries classification again.
                return None
        return self._cache[message]


class UnavailableCauseClassifier:
    def classify(self, message: str) -> ConflictCategory | None:
        return None
