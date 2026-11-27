"""The structural port every LLM-backed module depends on — a minimal text-in/text-out
call. Lives in the shared kernel, not any one module's ports.py: `mapping` and
`conflicts` both depend on it, and a port two modules share belongs where both can
import it without one reaching into the other's internals.

Concrete clients (Bedrock, Anthropic, Azure Foundry, OpenAI — see this package's other
files) implement it; the composition root injects one.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Protocol, TypeVar

if TYPE_CHECKING:
    from collections.abc import Callable

_T = TypeVar("_T")
_MAX_ATTEMPTS = 3


class LlmClient(Protocol):
    def ask(self, system: str, user: str) -> str: ...


def retry_with_backoff(call: Callable[[], _T], *, max_attempts: int = _MAX_ATTEMPTS) -> _T:
    """Retries `call` on any exception, with exponential backoff (2s, 4s, ...) between
    attempts. Shared by every LlmClient caller (mapping proposals, sample-request
    suggestions, conflict classification, conflict explanations) so a transient
    provider failure - the DNS flakiness this exact network has shown - gets one
    retry policy to tune, not one copy-pasted into each caller."""
    last_error: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            return call()
        except Exception as e:  # retry any provider/parse failure
            last_error = e
            if attempt < max_attempts:
                time.sleep(2**attempt)
    assert last_error is not None
    raise last_error
