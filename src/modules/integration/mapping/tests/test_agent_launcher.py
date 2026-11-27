from __future__ import annotations

from typing import TYPE_CHECKING, Any

import httpx

from src.modules.integration.mapping.domain.models import MappingEntry
from src.modules.integration.mapping.infrastructure.agent_launcher import HttpAdapterRunLauncher

if TYPE_CHECKING:
    import pytest


class _FakeResponse:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        pass

    def json(self) -> dict[str, Any]:
        return self._payload


def test_launch_sends_the_configured_bearer_token(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}

    def fake_post(url: str, json: Any, headers: dict[str, str], timeout: float) -> _FakeResponse:
        seen["headers"] = headers
        return _FakeResponse({"run_id": "run_1"})

    monkeypatch.setattr(httpx, "post", fake_post)
    launcher = HttpAdapterRunLauncher("http://agent", api_token="s3cr3t")
    entry = MappingEntry(erp_field="a", canonical_field="b", sample_data="c", confidence=90)

    launcher.launch("ODOO", [entry])

    assert seen["headers"] == {"Authorization": "Bearer s3cr3t"}


def test_launch_sends_no_auth_header_when_no_token_is_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: dict[str, Any] = {}

    def fake_post(url: str, json: Any, headers: dict[str, str], timeout: float) -> _FakeResponse:
        seen["headers"] = headers
        return _FakeResponse({"run_id": "run_1"})

    monkeypatch.setattr(httpx, "post", fake_post)
    launcher = HttpAdapterRunLauncher("http://agent")

    launcher.launch("ODOO", [])

    assert seen["headers"] == {}
