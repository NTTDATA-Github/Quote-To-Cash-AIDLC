import importlib

import pytest
from service.agent import build_task_prompt, is_erp_registered


def _fresh_agent_module(monkeypatch, **env):
    for key in ("TARGET_REPO_URL", "GITHUB_TOKEN", "REPO_CACHE_DIR", "WORKTREES_DIR"):
        monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    import service.agent as agent_module

    return importlib.reload(agent_module)


def test_build_task_prompt_new_erp_includes_checklist_and_mapping_rows():
    mapping = [
        {
            "erp_field": "KUNNR",
            "canonical_field": "erp_customer_id",
            "sample_data": "C1",
            "confidence": 97,
        },
        {
            "erp_field": "SMTP_ADDR",
            "canonical_field": "email",
            "sample_data": "a@b.com",
            "confidence": 90,
        },
    ]
    prompt = build_task_prompt("SAP", mapping, already_registered=False)
    assert "SAP" in prompt
    assert "docs/adding-an-erp.md" in prompt
    assert "KUNNR -> erp_customer_id (confidence 97%)" in prompt
    assert "SMTP_ADDR -> email (confidence 90%)" in prompt
    assert "composition.py" in prompt  # the "don't touch these" guardrail


def test_build_task_prompt_already_registered_says_update_not_add():
    prompt = build_task_prompt("Odoo", [], already_registered=True)
    assert "already has an ErpType registered" in prompt
    assert "do NOT add a new enum entry" in prompt


def test_build_task_prompt_handles_empty_mapping():
    prompt = build_task_prompt("TestERP", [], already_registered=False)
    assert "TestERP" in prompt


def test_build_task_prompt_distinguishes_account_specific_from_public_platform_unknowns():
    """Regression test: a real run left a bare placeholder for NetSuite's auth
    because the old prompt lumped "auth shape" in with genuinely account-specific
    unknowns (exact status values). Those need different treatment — the model
    should reason out a real default for publicly documented platform conventions,
    not TODO everything it wasn't handed directly in the mapping."""
    prompt = build_task_prompt("NetSuite", [], already_registered=False)
    assert "Account-specific unknowns" in prompt
    assert "write a clear TODO comment" in prompt
    assert "Publicly documented platform conventions" in prompt
    assert "implement a real, working default" in prompt
    assert "Never invent a value here" in prompt  # still applies to the account-specific half


def test_build_task_prompt_flags_low_confidence_rows_and_tells_agent_to_comment_them():
    mapping = [
        {"erp_field": "A", "canonical_field": "a", "sample_data": "1", "confidence": 98},
        {"erp_field": "B", "canonical_field": "b", "sample_data": "2", "confidence": 65},
    ]
    prompt = build_task_prompt("SAP", mapping, already_registered=False)
    assert "A -> a (confidence 98%)\n" in prompt  # high confidence: no flag
    assert "B -> b (confidence 65%) [LOW CONFIDENCE]" in prompt
    assert "add a short code comment" in prompt


def test_build_task_prompt_asks_for_docs_erps_page():
    prompt = build_task_prompt("NetSuite", [], already_registered=False)
    assert "docs/erps/netsuite.md" in prompt
    assert "docs/erps/README.md" in prompt


def test_build_task_prompt_forbids_self_commit():
    prompt = build_task_prompt("SAP", [], already_registered=False)
    assert "Do not run `git commit` or `git push` yourself" in prompt


def test_run_coding_agent_disallows_mutating_git_and_escalation_commands(monkeypatch, tmp_path):
    """Regression test for the security gap the prompt review surfaced: the coding
    agent had no tool restriction at all, unlike the earlier Kiro-agent design it was
    supposed to mirror. Defense in depth alongside the "don't commit" prompt text."""
    import service.agent as agent

    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd

        class _Result:
            returncode = 0
            stdout = "ok"
            stderr = ""

        return _Result()

    monkeypatch.setattr(agent.subprocess, "run", fake_run)
    agent.run_coding_agent(tmp_path, "do the thing")

    cmd = captured["cmd"]
    assert "--disallowedTools" in cmd
    disallowed = cmd[cmd.index("--disallowedTools") + 1 :]
    for pattern in [
        "Bash(git commit*)",
        "Bash(git push*)",
        "Bash(rm -rf*)",
        "Bash(sudo*)",
        "Bash(pip install*)",
        "Bash(docker*)",
    ]:
        assert pattern in disallowed


def test_ensure_repo_fails_clearly_without_target_repo_url(monkeypatch, tmp_path):
    agent = _fresh_agent_module(monkeypatch, REPO_CACHE_DIR=str(tmp_path / "cache"))
    with pytest.raises(agent.AgentRunError, match="TARGET_REPO_URL is not set"):
        agent.ensure_repo()


def test_auth_header_args_empty_without_token(monkeypatch):
    agent = _fresh_agent_module(monkeypatch)
    assert agent._auth_header_args() == []


def test_auth_header_args_injects_basic_auth_without_touching_remote_url(monkeypatch):
    agent = _fresh_agent_module(monkeypatch, GITHUB_TOKEN="my-token")
    args = agent._auth_header_args()
    assert args[0] == "-c"
    assert args[1].startswith("http.extraHeader=AUTHORIZATION: Basic ")
    assert "my-token" not in args[1]  # it's base64-encoded, not raw, in the header value


def test_auth_header_uses_real_github_username_not_x_access_token(monkeypatch):
    """Regression test for a live bug: using the literal string "x-access-token" as
    the Basic-auth username (the GitHub App convention) silently 403s a personal
    access token's push even when the token's own permissions are fine. The username
    must be the actual account from TARGET_REPO_URL."""
    import base64

    agent = _fresh_agent_module(
        monkeypatch,
        GITHUB_TOKEN="my-token",
        TARGET_REPO_URL="https://github.com/octocat/hello-world.git",
    )
    assert agent._repo_owner() == "octocat"
    args = agent._auth_header_args()
    basic_value = args[1].removeprefix("http.extraHeader=AUTHORIZATION: Basic ")
    decoded = base64.b64decode(basic_value).decode()
    assert decoded == "octocat:my-token"
    assert not decoded.startswith("x-access-token")


def test_is_erp_registered_true_for_existing_erp_type(tmp_path):
    models_dir = tmp_path / "src/modules/reference/connections/domain"
    models_dir.mkdir(parents=True)
    (models_dir / "models.py").write_text('class ErpType(str, Enum):\n    ODOO = "ODOO"\n')
    assert is_erp_registered(tmp_path, "Odoo") is True
    assert is_erp_registered(tmp_path, "odoo") is True


def test_is_erp_registered_false_for_unregistered_erp(tmp_path):
    models_dir = tmp_path / "src/modules/reference/connections/domain"
    models_dir.mkdir(parents=True)
    (models_dir / "models.py").write_text('class ErpType(str, Enum):\n    ODOO = "ODOO"\n')
    assert is_erp_registered(tmp_path, "NetSuite") is False


def test_is_erp_registered_ignores_mentions_outside_the_enum_body(tmp_path):
    """Regression test: a real run falsely flagged NetSuite as registered because a
    docstring/comment mentioned it as a hypothetical example ERP elsewhere in the same
    file. Only actual `NAME = "VALUE"` lines inside the ErpType class body count."""
    models_dir = tmp_path / "src/modules/reference/connections/domain"
    models_dir.mkdir(parents=True)
    (models_dir / "models.py").write_text(
        '"""credentials: a per-adapter-interpreted bag (NetSuite, ERPNext) might need '
        'an account id, or nothing at all."""\n'
        "class ErpType(str, Enum):\n"
        '    ODOO = "ODOO"\n'
    )
    assert is_erp_registered(tmp_path, "NetSuite") is False
    assert is_erp_registered(tmp_path, "ERPNext") is False
    assert is_erp_registered(tmp_path, "Odoo") is True


def test_failed_run_never_leaks_the_auth_header_into_the_error_message(monkeypatch, tmp_path):
    """Regression test: a failing authenticated git command (clone/fetch/push) must
    never echo the token back in AgentRunError's message — that message ends up in
    logs and in the /runs API response, both of which are far less protected than
    the .env file the token actually lives in."""
    agent = _fresh_agent_module(monkeypatch, GITHUB_TOKEN="super-secret-token-value")
    auth_args = agent._auth_header_args()
    cmd = ["git", *auth_args, "fetch", "origin", "main"]
    with pytest.raises(agent.AgentRunError) as exc_info:
        agent._run(cmd, cwd=tmp_path, timeout=5)  # tmp_path isn't a git repo -> fails
    message = str(exc_info.value)
    assert auth_args[1] not in message  # the base64-encoded header value itself
    assert "AUTHORIZATION" not in message
    assert "REDACTED" in message


MAPPING_A = [
    {
        "erp_field": "tranid",
        "canonical_field": "erp_order_id",
        "sample_data": "SO1",
        "confidence": 98,
    }
]
MAPPING_B = [
    {
        "erp_field": "tranid",
        "canonical_field": "erp_order_id",
        "sample_data": "SO1",
        "confidence": 60,
    }
]


def test_mapping_hash_same_input_same_hash_different_input_different_hash():
    from service.agent import _mapping_hash

    assert _mapping_hash(MAPPING_A) == _mapping_hash(MAPPING_A)
    assert _mapping_hash(MAPPING_A) != _mapping_hash(MAPPING_B)


def _fake_git_result(returncode=0, stdout=""):
    class _Result:
        pass

    r = _Result()
    r.returncode = returncode
    r.stdout = stdout
    return r


def test_find_stale_worktree_finds_a_clean_committed_match(monkeypatch, tmp_path):
    agent = _fresh_agent_module(monkeypatch, WORKTREES_DIR=str(tmp_path))
    wt = tmp_path / "agent" / "erp-netsuite-aaaa1111"
    wt.mkdir(parents=True)
    agent._hash_sidecar(f"agent/{wt.name}").write_text(agent._mapping_hash(MAPPING_A))

    def fake_run(cmd, **kwargs):
        if "status" in cmd:
            return _fake_git_result(0, "")  # clean working tree
        if "rev-list" in cmd:
            return _fake_git_result(0, "2")  # 2 commits ahead of main
        raise AssertionError(f"unexpected command: {cmd}")

    monkeypatch.setattr(agent.subprocess, "run", fake_run)
    result = agent.find_stale_worktree("NetSuite", MAPPING_A)
    assert result == (wt, f"agent/{wt.name}")


def test_find_stale_worktree_ignores_mismatched_mapping_hash(monkeypatch, tmp_path):
    agent = _fresh_agent_module(monkeypatch, WORKTREES_DIR=str(tmp_path))
    wt = tmp_path / "agent" / "erp-netsuite-bbbb2222"
    wt.mkdir(parents=True)
    agent._hash_sidecar(f"agent/{wt.name}").write_text(
        agent._mapping_hash(MAPPING_B)
    )  # different mapping

    called = []
    monkeypatch.setattr(
        agent.subprocess, "run", lambda *a, **k: called.append(a) or _fake_git_result()
    )
    result = agent.find_stale_worktree("NetSuite", MAPPING_A)
    assert result is None
    assert called == []  # never even shells out once the hash doesn't match


def test_find_stale_worktree_ignores_dirty_worktree(monkeypatch, tmp_path):
    agent = _fresh_agent_module(monkeypatch, WORKTREES_DIR=str(tmp_path))
    wt = tmp_path / "agent" / "erp-netsuite-cccc3333"
    wt.mkdir(parents=True)
    agent._hash_sidecar(f"agent/{wt.name}").write_text(agent._mapping_hash(MAPPING_A))

    monkeypatch.setattr(
        agent.subprocess, "run", lambda cmd, **k: _fake_git_result(0, "M some_file.py")
    )
    assert agent.find_stale_worktree("NetSuite", MAPPING_A) is None


def test_find_stale_worktree_ignores_worktree_with_nothing_ahead_of_main(monkeypatch, tmp_path):
    agent = _fresh_agent_module(monkeypatch, WORKTREES_DIR=str(tmp_path))
    wt = tmp_path / "agent" / "erp-netsuite-dddd4444"
    wt.mkdir(parents=True)
    agent._hash_sidecar(f"agent/{wt.name}").write_text(agent._mapping_hash(MAPPING_A))

    def fake_run(cmd, **kwargs):
        if "status" in cmd:
            return _fake_git_result(0, "")
        return _fake_git_result(0, "0")  # nothing committed beyond main

    monkeypatch.setattr(agent.subprocess, "run", fake_run)
    assert agent.find_stale_worktree("NetSuite", MAPPING_A) is None


def test_find_stale_worktree_returns_none_when_nothing_exists(monkeypatch, tmp_path):
    agent = _fresh_agent_module(monkeypatch, WORKTREES_DIR=str(tmp_path))
    assert agent.find_stale_worktree("NetSuite", MAPPING_A) is None


def test_repo_slug_strips_dot_git_suffix(monkeypatch):
    agent = _fresh_agent_module(
        monkeypatch, TARGET_REPO_URL="https://github.com/octocat/hello-world.git"
    )
    assert agent._repo_slug() == "octocat/hello-world"


def test_create_pull_request_posts_to_github_api_and_returns_html_url(monkeypatch):
    """Regression test: a live run showed `gh` isn't installed on this machine at
    all (FileNotFoundError, not a permission error), after push had already started
    working with a correctly-authenticated token. Calling GitHub's REST API directly
    removes the `gh` CLI as a dependency entirely."""
    import json as json_module

    agent = _fresh_agent_module(
        monkeypatch,
        GITHUB_TOKEN="my-token",
        TARGET_REPO_URL="https://github.com/octocat/hello-world.git",
    )
    captured = {}

    class _FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return json_module.dumps(
                {"html_url": "https://github.com/octocat/hello-world/pull/1"}
            ).encode()

    def fake_urlopen(req, timeout=None):
        captured["url"] = req.full_url
        captured["method"] = req.get_method()
        captured["headers"] = dict(req.header_items())
        captured["body"] = json_module.loads(req.data.decode())
        return _FakeResponse()

    monkeypatch.setattr(agent.urllib.request, "urlopen", fake_urlopen)
    result = agent.create_pull_request(
        "agent/erp-netsuite-abc", "Add NetSuite adapter", "body text"
    )

    assert result == "https://github.com/octocat/hello-world/pull/1"
    assert captured["url"] == "https://api.github.com/repos/octocat/hello-world/pulls"
    assert captured["method"] == "POST"
    assert captured["headers"]["Authorization"] == "Bearer my-token"
    assert captured["body"] == {
        "title": "Add NetSuite adapter",
        "body": "body text",
        "head": "agent/erp-netsuite-abc",
        "base": "main",
    }
