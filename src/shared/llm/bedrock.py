"""Amazon Bedrock Converse client — a generic `ask(system, user) -> str`.

Lives in the shared kernel (not in `src.modules`) because it imports `boto3`, which the
"framework-free" architecture contract forbids inside modules — same placement as the
other boto3-backed adapters (`shared/secrets/aws.py`, `shared/messaging/aws.py`). Knows
nothing about field mapping or any other caller; it just relays a prompt to Bedrock.

Bedrock (not Gemini/Anthropic) is the one provider the portal can use without a new
dependency — `boto3` is already a core dependency. Pick the model with
`MAPPING_BEDROCK_MODEL_ID`; it must be an on-demand-invokable id, which for most Claude
models means a cross-region inference profile id (the `us.`/`global.` prefix).
"""

from __future__ import annotations

import boto3

_MAX_TOKENS = 4096


class BedrockLlmClient:
    def __init__(self, model_id: str, region_name: str) -> None:
        self._model_id = model_id
        self._region_name = region_name
        self._client: object | None = None

    def _runtime(self) -> object:
        if self._client is None:
            self._client = boto3.client("bedrock-runtime", region_name=self._region_name)
        return self._client

    def ask(self, system: str, user: str, max_tokens: int = _MAX_TOKENS) -> str:
        response = self._runtime().converse(  # type: ignore[attr-defined]
            modelId=self._model_id,
            system=[{"text": system}],
            messages=[{"role": "user", "content": [{"text": user}]}],
            inferenceConfig={"maxTokens": max_tokens, "temperature": 0},
        )
        parts = response["output"]["message"]["content"]
        return "".join(p.get("text", "") for p in parts).strip()
