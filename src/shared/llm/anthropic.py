"""Direct Anthropic API client (ADR-0023) — replaces Bedrock on the Azure path.

Same `ask(system, user) -> str` shape as `BedrockLlmClient`, so `LlmMappingProposer` /
`LlmSampleRequestSuggester` don't change at all — only the composition root picks a
different client. Uses `urllib` (stdlib), the same way `bedrock.py`'s bearer-token path
already does, rather than adding the `anthropic` package as a new dependency for one
HTTP call.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

_MAX_TOKENS = 4096
_API_VERSION = "2023-06-01"
_MESSAGES_URL = "https://api.anthropic.com/v1/messages"


class AnthropicLlmClient:
    def __init__(self, model_id: str, api_key: str | None = None) -> None:
        self._model_id = model_id
        self._api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")

    def ask(self, system: str, user: str, max_tokens: int = _MAX_TOKENS) -> str:
        if not self._api_key:
            raise RuntimeError(
                "no Anthropic API key configured — set ANTHROPIC_API_KEY "
                "(sourced from Key Vault's anthropic-api-key secret in Azure)"
            )
        body = json.dumps(
            {
                "model": self._model_id,
                "max_tokens": max_tokens,
                "system": system,
                "messages": [{"role": "user", "content": user}],
                "temperature": 0,
            }
        ).encode()
        request = urllib.request.Request(
            _MESSAGES_URL,
            data=body,
            method="POST",
            headers={
                "x-api-key": self._api_key,
                "anthropic-version": _API_VERSION,
                "content-type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                payload = json.load(response)
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", errors="replace")[:500]
            raise RuntimeError(f"Anthropic messages call failed: {e.code} {detail}") from e
        return _text(payload)


def _text(payload: dict) -> str:  # type: ignore[type-arg]
    return "".join(part.get("text", "") for part in payload.get("content", [])).strip()
