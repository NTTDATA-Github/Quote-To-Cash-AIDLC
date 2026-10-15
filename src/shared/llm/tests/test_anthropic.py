from __future__ import annotations

import io
import json

import pytest
from src.shared.llm.anthropic import AnthropicLlmClient


def test_ask_posts_to_the_messages_api_and_extracts_text(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def fake_urlopen(request, timeout=0):  # type: ignore[no-untyped-def]
        captured["url"] = request.full_url
        captured["api_key"] = request.get_header("X-api-key")
        captured["body"] = json.loads(request.data)
        body = json.dumps({"content": [{"type": "text", "text": "hello"}]}).encode()
        return io.BytesIO(body)

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    text = AnthropicLlmClient("claude-haiku-4-5-20251001", api_key="sk-test").ask("sys", "usr")

    assert text == "hello"
    assert captured["url"] == "https://api.anthropic.com/v1/messages"
    assert captured["api_key"] == "sk-test"
    assert captured["body"] == {
        "model": "claude-haiku-4-5-20251001",
        "max_tokens": 4096,
        "system": "sys",
        "messages": [{"role": "user", "content": "usr"}],
        "temperature": 0,
    }


def test_no_api_key_raises_without_making_a_request(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    def fail_urlopen(*_args, **_kwargs):  # type: ignore[no-untyped-def]
        raise AssertionError("must not call out with no api key")

    monkeypatch.setattr("urllib.request.urlopen", fail_urlopen)

    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
        AnthropicLlmClient("claude-haiku-4-5-20251001").ask("sys", "usr")


def test_api_key_falls_back_to_the_environment_variable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-from-env")
    captured: dict[str, object] = {}

    def fake_urlopen(request, timeout=0):  # type: ignore[no-untyped-def]
        captured["api_key"] = request.get_header("X-api-key")
        body = json.dumps({"content": [{"type": "text", "text": "ok"}]}).encode()
        return io.BytesIO(body)

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    AnthropicLlmClient("claude-haiku-4-5-20251001").ask("sys", "usr")

    assert captured["api_key"] == "sk-from-env"
