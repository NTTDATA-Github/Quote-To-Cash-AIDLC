from __future__ import annotations

import io
import json

import pytest
from src.shared.llm.bedrock import BedrockLlmClient

_FAKE_TOKEN = "test-token"


@pytest.fixture(autouse=True)
def discard_real_bedrock_token(monkeypatch: pytest.MonkeyPatch) -> None:
    """Never let a developer token in the environment reach a test."""
    monkeypatch.delenv("AWS_BEARER_TOKEN_BEDROCK", raising=False)


def test_bearer_token_calls_real_bedrock_not_the_local_endpoint(monkeypatch) -> None:
    monkeypatch.setenv("AWS_ENDPOINT_URL", "http://127.0.0.1:9")
    monkeypatch.setenv("AWS_BEARER_TOKEN_BEDROCK", _FAKE_TOKEN)
    captured: dict[str, str] = {}

    def fake_urlopen(request, timeout=0):  # type: ignore[no-untyped-def]
        captured["url"] = request.full_url
        captured["auth"] = request.get_header("Authorization")
        body = json.dumps({"output": {"message": {"content": [{"text": "[]"}]}}}).encode()
        return io.BytesIO(body)

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    text = BedrockLlmClient("us.anthropic.claude-haiku-4-5-20251001-v1:0", "us-east-1").ask(
        "s", "u"
    )

    assert text == "[]"
    assert captured["url"].startswith("https://bedrock-runtime.us-east-1.amazonaws.com/model/")
    assert "4566" not in captured["url"]
    assert "%3A" in captured["url"]
    assert captured["auth"] == f"Bearer {_FAKE_TOKEN}"


def test_local_endpoint_without_a_bearer_token_does_not_call_the_emulator(monkeypatch) -> None:
    monkeypatch.setenv("AWS_ENDPOINT_URL", "http://127.0.0.1:9")
    with pytest.raises(RuntimeError, match="AWS_BEARER_TOKEN_BEDROCK"):
        BedrockLlmClient("model", "us-east-1").ask("s", "u")
