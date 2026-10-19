"""OpenAI LLM client — GPT models via OpenAI API or Azure Foundry.

Same `ask(system, user) -> str` interface as Bedrock/Anthropic/Foundry clients.
Works with both OpenAI's direct API and Azure Foundry's OpenAI endpoint.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request

_MAX_TOKENS = 4096
_AZURE_API_VERSION = "2024-10-21"
# Azure AI / OpenAI resource hosts: <name>.cognitiveservices.azure.com, <name>.openai.azure.com,
# and the regional <region>.api.cognitive.microsoft.com that azurerm outputs.
_AZURE_HOST_SUFFIXES = (".azure.com", ".cognitive.microsoft.com")


class OpenAiLlmClient:
    def __init__(self, endpoint_url: str, api_key: str, model_id: str) -> None:
        """
        Args:
            endpoint_url: https://api.openai.com/v1, or an Azure resource endpoint
                (https://<region>.api.cognitive.microsoft.com or <name>.cognitiveservices.azure.com)
            api_key: API key for authentication
            model_id: Model name (e.g., "gpt-4o", "gpt-5")
        """
        self._endpoint = endpoint_url.rstrip("/")
        self._api_key = api_key
        self._model_id = model_id
        host = urllib.parse.urlparse(endpoint_url).hostname or ""
        self._is_azure = host.endswith(_AZURE_HOST_SUFFIXES)

    def ask(self, system: str, user: str, max_tokens: int = _MAX_TOKENS) -> str:
        if not self._api_key:
            raise RuntimeError(
                "no OpenAI-format API key configured — set FOUNDRY_API_KEY "
                "(sourced from Key Vault's foundry-api-key secret)"
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
        headers = {
            "content-type": "application/json",
        }
        if self._is_azure:
            # Azure routes by deployment name (== model_id) and requires an api-version.
            url = (
                f"{self._endpoint}/openai/deployments/{self._model_id}"
                f"/chat/completions?api-version={_AZURE_API_VERSION}"
            )
            headers["api-key"] = self._api_key
        else:
            url = f"{self._endpoint}/chat/completions"
            headers["Authorization"] = f"Bearer {self._api_key}"

        request = urllib.request.Request(
            url,
            data=body,
            method="POST",
            headers=headers,
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
