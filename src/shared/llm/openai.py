"""OpenAI LLM client — GPT models via OpenAI API or Azure Foundry.

Same `ask(system, user) -> str` interface as Bedrock/Anthropic/Foundry clients.
Works with both OpenAI's direct API and Azure Foundry's OpenAI endpoint.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request

_MAX_TOKENS = 4096


class OpenAiLlmClient:
    def __init__(self, endpoint_url: str, api_key: str, model_id: str) -> None:
        """
        Args:
            endpoint_url: OpenAI API endpoint (https://api.openai.com/v1 or Azure Foundry URL)
            api_key: API key for authentication
            model_id: Model name (e.g., "gpt-4o", "gpt-5")
        """
        self._endpoint = endpoint_url.rstrip("/")
        self._api_key = api_key
        self._model_id = model_id

    def ask(self, system: str, user: str, max_tokens: int = _MAX_TOKENS) -> str:
        if not self._api_key:
            raise RuntimeError(
                "no OpenAI API key configured — set OPENAI_API_KEY "
                "(sourced from Key Vault's openai-api-key secret)"
            )
        body = json.dumps(
            {
                "model": self._model_id,
                "max_tokens": max_tokens,
                "temperature": 0,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            }
        ).encode()
        request = urllib.request.Request(
            f"{self._endpoint}/chat/completions",
            data=body,
            method="POST",
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "content-type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                payload = json.load(response)
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", errors="replace")[:500]
            raise RuntimeError(f"OpenAI API call failed: {e.code} {detail}") from e
        return _text(payload)


def _text(payload: dict) -> str:  # type: ignore[type-arg]
    try:
        return payload.get("choices", [{}])[0].get("message", {}).get("content", "").strip()
    except (IndexError, KeyError, AttributeError):
        return ""
