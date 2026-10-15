"""LLM client adapters (cloud SDKs live in the shared kernel, never in `src.modules` —
the import-linter "framework-free" contract forbids boto3 inside modules). A module that
needs an LLM depends on a structural `ask(system, user) -> str` client and gets a concrete
one injected by the composition root."""

from __future__ import annotations

from .anthropic import AnthropicLlmClient
from .bedrock import BedrockLlmClient

__all__ = ["AnthropicLlmClient", "BedrockLlmClient"]
