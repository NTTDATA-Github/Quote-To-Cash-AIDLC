"""Amazon Bedrock Converse client — a generic `ask(system, user) -> str`.

Lives in the shared kernel (not in `src.modules`) because it imports `boto3`, which the
"framework-free" architecture contract forbids inside modules — same placement as the
other cloud-SDK adapters (`shared/secrets/azure.py`, `shared/messaging/azure.py`). Knows
nothing about field mapping or any other caller; it just relays a prompt to Bedrock.

Bedrock (not Gemini/Anthropic) is the one provider the portal can use without a new
dependency — `boto3` is already a core dependency. Pick the model with
`MAPPING_BEDROCK_MODEL_ID`; it must be an on-demand-invokable id, which for most Claude
models means a cross-region inference profile id (the `us.`/`global.` prefix).
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from urllib.parse import quote

import boto3

_MAX_TOKENS = 4096


class BedrockLlmClient:
    def __init__(self, model_id: str, region_name: str) -> None:
        self._model_id = model_id
        self._region_name = region_name
        self._client: object | None = None

    def _runtime(self) -> object:
        if self._client is None:
            # No endpoint_url, so boto3 talks to real Bedrock.
            self._client = boto3.client("bedrock-runtime", region_name=self._region_name)
        return self._client

    def ask(self, system: str, user: str, max_tokens: int = _MAX_TOKENS) -> str:
        token = os.environ.get("AWS_BEARER_TOKEN_BEDROCK", "").strip()
        if token:
            # Bearer auth goes to the real Converse endpoint.
            return self._ask_bearer(token, system, user, max_tokens)
        if os.environ.get("AWS_ENDPOINT_URL"):
            raise RuntimeError(
                "AWS_ENDPOINT_URL sends Bedrock to a non-AWS endpoint, which doesn't serve real "
                "mappings. Set AWS_BEARER_TOKEN_BEDROCK to call the real Converse API."
            )
        response = self._runtime().converse(  # type: ignore[attr-defined]
            modelId=self._model_id,
            system=[{"text": system}],
            messages=[{"role": "user", "content": [{"text": user}]}],
            inferenceConfig={"maxTokens": max_tokens, "temperature": 0},
        )
        return _text(response)

    def _ask_bearer(self, token: str, system: str, user: str, max_tokens: int) -> str:
        url = (
            f"https://bedrock-runtime.{self._region_name}.amazonaws.com"
            f"/model/{quote(self._model_id, safe='')}/converse"
        )
        body = json.dumps(
            {
                "system": [{"text": system}],
                "messages": [{"role": "user", "content": [{"text": user}]}],
                "inferenceConfig": {"maxTokens": max_tokens, "temperature": 0},
            }
        ).encode()
        request = urllib.request.Request(
            url,
            data=body,
            method="POST",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                payload = json.load(response)
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", errors="replace")[:500]
            raise RuntimeError(f"Bedrock converse failed: {e.code} {detail}") from e
        return _text(payload)


def _text(response: dict) -> str:  # type: ignore[type-arg]
    parts = response["output"]["message"]["content"]
    return "".join(p.get("text", "") for p in parts).strip()
