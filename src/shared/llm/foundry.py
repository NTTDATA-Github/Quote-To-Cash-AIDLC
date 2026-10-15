"""Azure Foundry LLM client (ADR-0023 extension) — Claude models via Microsoft Foundry.

Same `ask(system, user) -> str` shape as `BedrockLlmClient` / `AnthropicLlmClient`, so
`LlmMappingProposer` / `LlmSampleRequestSuggester` don't change at all — only the
composition root picks a different client. Foundry serves the Anthropic Messages API,
so the request/response shape is identical to AnthropicLlmClient; only the endpoint
and auth differ.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request

_MAX_TOKENS = 4096


class AzureFoundryLlmClient:
    def __init__(self, endpoint_url: str, api_key: str, model_id: str) -> None:
        """
        Args:
            endpoint_url: Azure Foundry endpoint (e.g., https://<region>.api.foundry.azure.com/...)
            api_key: API key for the deployment
            model_id: Model name (e.g., "claude-haiku-5-5")
        """
        self._endpoint = endpoint_url.rstrip("/")
        self._api_key = api_key
        self._model_id = model_id

    def ask(self, system: str, user: str, max_tokens: int = _MAX_TOKENS) -> str:
        if not self._api_key:
            raise RuntimeError(
                "no Azure Foundry API key configured — set FOUNDRY_API_KEY "
                "(sourced from Key Vault's foundry-api-key secret in Azure)"
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
            f"{self._endpoint}/v1/messages",
            data=body,
            method="POST",
            headers={
                "api-key": self._api_key,
                "content-type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                payload = json.load(response)
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", errors="replace")[:500]
            raise RuntimeError(f"Foundry messages call failed: {e.code} {detail}") from e
        return _text(payload)


def _text(payload: dict) -> str:  # type: ignore[type-arg]
    return "".join(part.get("text", "") for part in payload.get("content", [])).strip()
