import importlib

from fastapi.testclient import TestClient

_PAYLOAD = {
    "erp_name": "ODOO",
    "mapping": [{"erp_field": "a", "canonical_field": "b", "sample_data": "c", "confidence": 90}],
}


def _fresh_app(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'test.db'}")
    import service.app as app_module

    return importlib.reload(app_module)


def test_runs_refuses_everything_when_no_token_is_configured(tmp_path, monkeypatch):
    app_module = _fresh_app(tmp_path, monkeypatch)
    # After the reload, not before: load_dotenv() only fills in vars that are missing,
    # so deleting it here (post-import) is what actually keeps it unset for this request
    # — deleting first would just let the reload below repopulate it from the real .env.
    monkeypatch.delenv("AGENT_API_TOKEN", raising=False)
    client = TestClient(app_module.app)

    response = client.post("/runs", json=_PAYLOAD)

    assert response.status_code == 500


def test_runs_rejects_a_missing_or_wrong_token(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_API_TOKEN", "right-token")
    app_module = _fresh_app(tmp_path, monkeypatch)
    client = TestClient(app_module.app)

    no_header = client.post("/runs", json=_PAYLOAD)
    wrong_token = client.post(
        "/runs", json=_PAYLOAD, headers={"Authorization": "Bearer wrong-token"}
    )

    assert no_header.status_code == 401
    assert wrong_token.status_code == 401


def test_runs_accepts_the_right_bearer_token(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_API_TOKEN", "right-token")
    app_module = _fresh_app(tmp_path, monkeypatch)
    client = TestClient(app_module.app)

    response = client.post("/runs", json=_PAYLOAD, headers={"Authorization": "Bearer right-token"})

    assert response.status_code == 200
    assert response.json()["status"] == "PENDING"


def test_runs_rejects_an_erp_name_with_a_path_separator(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_API_TOKEN", "right-token")
    app_module = _fresh_app(tmp_path, monkeypatch)
    client = TestClient(app_module.app)

    payload = {**_PAYLOAD, "erp_name": "../../etc/passwd"}
    response = client.post("/runs", json=payload, headers={"Authorization": "Bearer right-token"})

    assert response.status_code == 422


def test_livez_needs_no_token(tmp_path, monkeypatch):
    monkeypatch.delenv("AGENT_API_TOKEN", raising=False)
    app_module = _fresh_app(tmp_path, monkeypatch)
    client = TestClient(app_module.app)

    assert client.get("/livez").status_code == 200
