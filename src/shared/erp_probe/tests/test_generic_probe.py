"""`GenericErpProbe` exercised against a real local HTTP server — not mocked — so the
request-building, auth-header application, and JSON/CSV extension detection are proven
end to end. The SSRF guard is bypassed here (the test server is necessarily loopback);
`src/shared/net/tests/test_ssrf_guard.py` is what actually proves it blocks loopback/
private/metadata addresses.
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from src.shared.erp_auth import AuthConfig, AuthType
from src.shared.erp_probe import GenericErpProbe, SampleRequestSpec
from src.shared.erp_probe import generic as probe_module
from src.shared.secrets import EnvSecretStore


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:
        pass  # quiet test output

    def do_GET(self) -> None:
        if self.path == "/boom":
            self.send_response(500)
            self.end_headers()
            self.wfile.write(b"server error")
            return
        if self.path.startswith("/orders"):
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            body = json.dumps([{"received_auth": self.headers.get("Authorization", "")}]).encode()
            self.wfile.write(body)
            return
        if self.path.startswith("/catalog"):
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            body = json.dumps([{"id": i, "name": "n" * 30} for i in range(20)]).encode()
            self.wfile.write(body)
            return
        if self.path.startswith("/customers"):
            self.send_response(200)
            self.send_header("Content-Type", "text/csv")
            self.end_headers()
            self.wfile.write(b"NAME,ID\nAcme,1\n")
            return
        self.send_response(404)
        self.end_headers()


@pytest.fixture
def server(monkeypatch: pytest.MonkeyPatch):
    httpd = HTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    # The test server is necessarily loopback — bypass the SSRF guard just for this test;
    # production code always goes through it (see module docstring above).
    monkeypatch.setattr(probe_module, "validate_outbound_url", lambda url: None)
    try:
        yield f"http://127.0.0.1:{httpd.server_port}"
    finally:
        httpd.shutdown()
        thread.join(timeout=2)


def test_applies_bearer_auth_and_detects_json(server: str) -> None:
    secrets = EnvSecretStore()
    secrets.put_secret("probe/test-token", "tok_abc")
    fetcher = GenericErpProbe(secrets)

    [sample] = fetcher.fetch_samples(
        base_url=server,
        auth=AuthConfig(auth_type=AuthType.BEARER_TOKEN),
        secret_ref="probe/test-token",
        requests=[SampleRequestSpec(label="orders", path="/orders")],
    )

    assert sample.error is None
    assert sample.label == "orders.json"
    assert json.loads(sample.text)[0]["received_auth"] == "Bearer tok_abc"


def test_capped_json_array_keeps_complete_records(
    server: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(probe_module, "_MAX_BODY_BYTES", 80)
    fetcher = GenericErpProbe(EnvSecretStore())
    [sample] = fetcher.fetch_samples(
        base_url=server,
        auth=AuthConfig(auth_type=AuthType.NONE),
        secret_ref=None,
        requests=[SampleRequestSpec(label="catalog", path="/catalog")],
    )
    assert sample.error is None
    records = json.loads(sample.text)
    assert records
    assert records[0]["id"] == 0


def test_detects_csv_from_content_type(server: str) -> None:
    fetcher = GenericErpProbe(EnvSecretStore())
    [sample] = fetcher.fetch_samples(
        base_url=server,
        auth=AuthConfig(auth_type=AuthType.NONE),
        secret_ref=None,
        requests=[SampleRequestSpec(label="customers", path="/customers")],
    )
    assert sample.error is None
    assert sample.label == "customers.csv"
    assert "Acme" in sample.text


def test_one_failed_request_does_not_sink_the_others(server: str) -> None:
    fetcher = GenericErpProbe(EnvSecretStore())
    results = fetcher.fetch_samples(
        base_url=server,
        auth=AuthConfig(auth_type=AuthType.NONE),
        secret_ref=None,
        requests=[
            SampleRequestSpec(label="broken", path="/boom"),
            SampleRequestSpec(label="orders", path="/orders"),
        ],
    )
    broken, orders = results
    assert broken.error is not None and "500" in broken.error
    assert orders.error is None and orders.text is not None


def test_missing_secret_fails_every_request_with_no_network_call(server: str) -> None:
    fetcher = GenericErpProbe(EnvSecretStore())
    results = fetcher.fetch_samples(
        base_url=server,
        auth=AuthConfig(auth_type=AuthType.BEARER_TOKEN),
        secret_ref=None,  # no secret resolved -> the strategy itself should reject
        requests=[SampleRequestSpec(label="orders", path="/orders")],
    )
    [sample] = results
    assert sample.error is not None and "requires a secret" in sample.error
