from __future__ import annotations

import pytest
from src.shared.llm.client import retry_with_backoff


def test_succeeds_immediately_without_retrying() -> None:
    calls: list[int] = []

    def call() -> str:
        calls.append(1)
        return "ok"

    assert retry_with_backoff(call) == "ok"
    assert len(calls) == 1


def test_retries_on_failure_and_returns_the_eventual_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("src.shared.llm.client.time.sleep", lambda _seconds: None)
    attempts: list[int] = []

    def call() -> str:
        attempts.append(1)
        if len(attempts) < 3:
            raise RuntimeError("transient")
        return "ok"

    assert retry_with_backoff(call) == "ok"
    assert len(attempts) == 3


def test_raises_the_last_error_once_every_attempt_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("src.shared.llm.client.time.sleep", lambda _seconds: None)
    attempts: list[int] = []

    def call() -> str:
        attempts.append(1)
        raise RuntimeError(f"failure {len(attempts)}")

    with pytest.raises(RuntimeError, match="failure 3"):
        retry_with_backoff(call, max_attempts=3)
    assert len(attempts) == 3


def test_max_attempts_is_configurable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("src.shared.llm.client.time.sleep", lambda _seconds: None)
    attempts: list[int] = []

    def call() -> str:
        attempts.append(1)
        raise RuntimeError("always fails")

    with pytest.raises(RuntimeError):
        retry_with_backoff(call, max_attempts=1)
    assert len(attempts) == 1
