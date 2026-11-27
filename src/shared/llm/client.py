"""The structural port every LLM-backed module depends on — a minimal text-in/text-out
call. Lives in the shared kernel, not any one module's ports.py: `mapping` and
`conflicts` both depend on it, and a port two modules share belongs where both can
import it without one reaching into the other's internals.

Concrete clients (Bedrock, Anthropic, Azure Foundry, OpenAI — see this package's other
files) implement it; the composition root injects one.
"""

from __future__ import annotations

from typing import Protocol


class LlmClient(Protocol):
    def ask(self, system: str, user: str) -> str: ...
