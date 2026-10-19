from __future__ import annotations

import io
import json

import pytest
from src.shared.llm.openai import OpenAiLlmClient

_REPLY = json.dumps({"choices": [{"message": {"content": " hello "}}]}).encode()


def _capture(monkeypatch: pytest.MonkeyPatch) -> dict[str, object]:
    captured: dict[str, object] = {}

    def fake_urlopen(request, timeout=0):  # type: ignore[no-untyped-def]
        captured["url"] = request.full_url
        captured["api_key"] = request.get_header("Api-key")
        captured["authorization"] = request.get_header("Authorization")
        captured["body"] = json.loads(request.data)
        return io.BytesIO(_REPLY)

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    return captured


def test_azure_endpoint_uses_deployment_url_and_api_key_header(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = _capture(monkeypatch)

    text = OpenAiLlmClient(
        "https://o2c-staging-foundry.cognitiveservices.azure.com/", "k", "gpt-4o"
    ).ask("sys", "usr")

    assert text == "hello"
    assert captured["url"] == (
        "https://o2c-staging-foundry.cognitiveservices.azure.com"
        "/openai/deployments/gpt-4o/chat/completions?api-version=2024-10-21"
    )
    assert captured["api_key"] == "k"
    assert captured["authorization"] is None
    assert captured["body"]["messages"] == [  # type: ignore[index]
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "usr"},
    ]


def test_regional_cognitive_endpoint_from_terraform_is_treated_as_azure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = _capture(monkeypatch)

    OpenAiLlmClient("https://eastus.api.cognitive.microsoft.com/", "k", "gpt-4o").ask("s", "u")

    assert captured["url"] == (
        "https://eastus.api.cognitive.microsoft.com"
        "/openai/deployments/gpt-4o/chat/completions?api-version=2024-10-21"
    )
    assert captured["api_key"] == "k"
    assert captured["authorization"] is None


def test_openai_endpoint_uses_bearer_token(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = _capture(monkeypatch)

    OpenAiLlmClient("https://api.openai.com/v1", "sk-test", "gpt-4o").ask("sys", "usr")

    assert captured["url"] == "https://api.openai.com/v1/chat/completions"
    assert captured["authorization"] == "Bearer sk-test"
    assert captured["api_key"] is None


def test_no_api_key_raises_without_making_a_request(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail_urlopen(*_args, **_kwargs):  # type: ignore[no-untyped-def]
        raise AssertionError("must not call out with no api key")

    monkeypatch.setattr("urllib.request.urlopen", fail_urlopen)

    with pytest.raises(RuntimeError, match="FOUNDRY_API_KEY"):
        OpenAiLlmClient("https://x.cognitiveservices.azure.com", "", "gpt-4o").ask("s", "u")
