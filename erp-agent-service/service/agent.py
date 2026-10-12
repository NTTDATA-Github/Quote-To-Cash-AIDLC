"""Turns an approved ERP field mapping into actual adapter code: clones (or refreshes
its own cached clone of) the target repo, creates an isolated git worktree + branch
from it, runs Claude Code headlessly against a task prompt built from the mapping,
runs tests, then commits, pushes, and opens a PR.

This service owns getting the repo — it does NOT assume it's deployed sitting next to
an already-checked-out copy (that was a local-dev shortcut this module used to take;
it breaks the moment this runs in a container with nothing pre-existing on disk).
TARGET_REPO_URL + GITHUB_TOKEN are what make this work anywhere: a fresh container
clones on first use, then reuses and refreshes that one clone for every later run,
with worktrees branching off it per-run for isolation.

Needs git, the `gh` CLI, and the `claude` CLI on whatever machine runs it.

Auth:
  - Git clone/fetch/push: GITHUB_TOKEN, injected as a Basic auth header per-command
    (never written into the stored remote URL or git config on disk).
  - `gh pr create`: reads GH_TOKEN/GITHUB_TOKEN from the environment automatically —
    no `gh auth login` needed, just export the token (same one works for both).
  - `claude` CLI: CLAUDE_CODE_USE_BEDROCK=1 (+ AWS_REGION, AWS_BEARER_TOKEN_BEDROCK or
    normal AWS credentials), or ANTHROPIC_API_KEY. See
    https://code.claude.com/docs/en/amazon-bedrock.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import re
import subprocess
import time
import urllib.error
import urllib.request
import uuid
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlparse

log = logging.getLogger("agent")

TARGET_REPO_URL = os.environ.get("TARGET_REPO_URL", "")
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
REPO_CACHE_DIR = Path(os.environ.get("REPO_CACHE_DIR", "./repo-cache")).resolve()
WORKTREES_DIR = Path(os.environ.get("WORKTREES_DIR", "./worktrees")).resolve()

AGENT_TIMEOUT_SECONDS = int(os.environ.get("AGENT_TIMEOUT_SECONDS", "1800"))
# Unpinned, Claude Code on Bedrock defaults its primary model to Opus — priced well
# above what a scoped, pattern-following task like "implement this adapter" needs.
# Sonnet is the right default for this task; override via env if you want something else.
CODING_AGENT_MODEL = os.environ.get("CODING_AGENT_MODEL", "us.anthropic.claude-sonnet-5")


class AgentRunError(Exception):
    pass


@contextmanager
def _step(name: str):
    """Logs start/end + elapsed time for one phase of a run, so a failure shows
    exactly which phase it happened in and how long that phase had been running —
    not just a final error with no sense of where in the run it occurred."""
    log.info("start: %s", name)
    t0 = time.monotonic()
    try:
        yield
    except Exception as e:
        log.error(
            "FAILED: %s after %.1fs — %s: %s", name, time.monotonic() - t0, type(e).__name__, e
        )
        raise
    else:
        log.info("done: %s (%.1fs)", name, time.monotonic() - t0)


ERP_TYPE_FILE = "src/modules/reference/connections/domain/models.py"


_ERP_TYPE_CLASS = re.compile(r"class ErpType\(.*?\):(.*?)(?:\nclass |\Z)", re.S)
_ENUM_ASSIGNMENT = re.compile(r'^\s*\w+\s*=\s*["\']([A-Za-z0-9_]+)["\']', re.M)


def is_erp_registered(worktree_path: Path, erp_name: str) -> bool:
    """Whether erp_name already has an ErpType entry. Parses only the actual enum
    value assignments inside the ErpType class body — a whole-file substring match
    was fooled by a comment mentioning an unregistered ERP as a hypothetical example
    (see ADR-0012's "(NetSuite, ERPNext) might need..." line)."""
    text = (worktree_path / ERP_TYPE_FILE).read_text()
    class_match = _ERP_TYPE_CLASS.search(text)
    body = class_match.group(1) if class_match else ""
    values = {v.upper() for v in _ENUM_ASSIGNMENT.findall(body)}
    needle = erp_name.strip().upper().replace(" ", "_").replace("-", "_")
    return needle in values


LOW_CONFIDENCE_THRESHOLD = 80


def build_task_prompt(erp_name: str, mapping: list[dict], already_registered: bool) -> str:
    mapping_table = "\n".join(
        f"- {m['erp_field']} -> {m['canonical_field']} (confidence {m['confidence']}%)"
        + (" [LOW CONFIDENCE]" if m["confidence"] < LOW_CONFIDENCE_THRESHOLD else "")
        for m in mapping
    )
    if already_registered:
        task = f"""This platform already has an ErpType registered for {erp_name} — do \
NOT add a new enum entry, a new adapter file, or a new registry line, those already \
exist. Find the existing adapter and status mapper for {erp_name} ({ERP_TYPE_FILE} \
names the enum value; docs/erps/ has a page per registered ERP) and update them so \
the field reads/writes and status mapping match this approved mapping exactly. Only \
touch what's actually wrong or missing against the mapping below — don't rewrite \
code that already matches it."""
    else:
        task = f"""Follow docs/adding-an-erp.md's 4-step checklist to register a new \
ERP type: {erp_name}."""

    return f"""{task}

Use this human-reviewed field mapping as the authoritative canonical<->ERP field \
correspondence for the payload-building and status-mapping code — do not re-derive \
field meanings from scratch, and do not second-guess a mapping that's already been \
approved:

{mapping_table}

Two different kinds of "unknown" need two different responses — don't collapse them \
into the same TODO treatment:
- Account-specific unknowns (this account's exact status field values, custom field \
IDs, anything that genuinely can't be known without a live account or that account's \
own API docs): write a clear TODO comment naming exactly what's missing. Never invent \
a value here.
- Publicly documented platform conventions ({erp_name}'s own supported auth \
protocols, its general API request/response shape, standard endpoint conventions): \
use your own knowledge of {erp_name}'s public API to implement a real, working \
default — don't leave a bare placeholder just because nothing here handed it to you \
on a plate. Prefer whichever option {erp_name}'s own docs currently recommend for new \
integrations over a legacy/deprecated one. Label the choice clearly in a comment as \
an assumption from {erp_name}'s public API documentation, to be verified against the \
real account, so a reviewer knows it's a reasoned default, not a guess and not a gap.

Any mapping row marked [LOW CONFIDENCE] above was approved under {LOW_CONFIDENCE_THRESHOLD}% \
confidence — still implement it as given (it's approved, not up for you to second-guess), \
but add a short code comment at the point you wire that specific field in, noting it was \
a low-confidence approved mapping, so a human reviewing the PR knows exactly which fields \
most deserve a second look.

Also add docs/erps/{erp_name.lower().replace(' ', '-')}.md following the section headings \
in docs/erps/README.md (and that file's own instructions for registering a new page there) \
— easy to miss since it isn't one of docs/adding-an-erp.md's 4 numbered steps, but it's \
this project's own convention for every registered ERP.

Do not run `git commit` or `git push` yourself — leave all changes as uncommitted edits \
in the working tree. A separate step outside this session handles staging, committing, \
pushing, and opening the PR; if you commit first, that step finds nothing left to commit \
and the whole run fails.

Keep the diff scoped to {erp_name}'s own adapter/status-mapper/registry/enum touch \
points — do not edit composition.py, DeliveryHandler, ReconcileSweeper, or the \
webhook ingress route, and do not touch any other ERP's files. Run the relevant unit \
tests when done (mock the HTTP layer, never a live ERP).
"""


def _repo_owner() -> str:
    """The GitHub username/org in TARGET_REPO_URL's path, e.g. "octocat" from
    https://github.com/octocat/repo.git — used as the Basic-auth username below."""
    path = urlparse(TARGET_REPO_URL).path.strip("/")
    return path.split("/")[0] if path else ""


def _auth_header_args() -> list[str]:
    """`-c http.extraHeader=...` for one git invocation — kept off the stored remote
    URL / git config so the token never lands on disk outside this one process call.

    Username must be the actual GitHub account, not the literal string
    "x-access-token" — that convention is for GitHub App installation tokens, which
    have no associated human account. Using it with a personal access token (classic
    or fine-grained) authenticates as nobody and silently 403s on push, even when the
    token itself is correctly scoped (confirmed live: GitHub's own API reported
    push: true for a token that still failed `git push` under the wrong username)."""
    if not GITHUB_TOKEN:
        return []
    basic = base64.b64encode(f"{_repo_owner()}:{GITHUB_TOKEN}".encode()).decode()
    return ["-c", f"http.extraHeader=AUTHORIZATION: Basic {basic}"]


def _redact(cmd: list[str]) -> list[str]:
    """For error messages/logs — _auth_header_args() puts the token in an
    http.extraHeader argument; never let that reach an exception message, a log
    line, or an API response, even though it's never written to disk."""
    out = []
    skip_next = False
    for arg in cmd:
        if skip_next:
            out.append("***REDACTED***" if "AUTHORIZATION" in arg else arg)
            skip_next = False
        else:
            out.append(arg)
            skip_next = arg == "-c"
    return out


def _run(cmd: list[str], cwd: Path, timeout: int) -> str:
    # encoding/errors explicit: on Windows, text=True defaults to the system codepage
    # (cp1252 here), which crashes a background reader thread the moment git/claude
    # output contains a character it can't represent (seen live: a UnicodeDecodeError
    # mid-run). UTF-8 with replacement never crashes and never silently drops output.
    result = subprocess.run(
        cmd,
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )
    if result.returncode != 0:
        raise AgentRunError(
            f"{' '.join(_redact(cmd))} failed (exit {result.returncode}):\n{result.stdout}\n{result.stderr}"
        )
    return result.stdout


def ensure_repo() -> None:
    """Clones TARGET_REPO_URL into REPO_CACHE_DIR on first use; on later runs, fetches
    and fast-forwards main instead of re-cloning. This cached clone is never edited
    directly — only worktrees created from it are."""
    if not TARGET_REPO_URL:
        raise AgentRunError("TARGET_REPO_URL is not set — see .env.example")
    if not (REPO_CACHE_DIR / ".git").exists():
        REPO_CACHE_DIR.parent.mkdir(parents=True, exist_ok=True)
        _run(
            ["git", *_auth_header_args(), "clone", TARGET_REPO_URL, str(REPO_CACHE_DIR)],
            cwd=REPO_CACHE_DIR.parent,
            timeout=300,
        )
    else:
        _run(
            ["git", *_auth_header_args(), "fetch", "origin", "main"],
            cwd=REPO_CACHE_DIR,
            timeout=120,
        )
        _run(["git", "checkout", "main"], cwd=REPO_CACHE_DIR, timeout=30)
        _run(["git", "reset", "--hard", "origin/main"], cwd=REPO_CACHE_DIR, timeout=30)


def create_worktree(branch_name: str) -> Path:
    ensure_repo()
    WORKTREES_DIR.mkdir(parents=True, exist_ok=True)
    path = WORKTREES_DIR / branch_name
    _run(
        ["git", "worktree", "add", str(path), "-b", branch_name, "origin/main"],
        cwd=REPO_CACHE_DIR,
        timeout=60,
    )
    return path


def remove_worktree(path: Path, branch_name: str) -> None:
    subprocess.run(
        ["git", "worktree", "remove", "--force", str(path)], cwd=REPO_CACHE_DIR, capture_output=True
    )
    subprocess.run(["git", "branch", "-D", branch_name], cwd=REPO_CACHE_DIR, capture_output=True)


def _mapping_hash(mapping: list[dict]) -> str:
    return hashlib.sha256(json.dumps(mapping, sort_keys=True).encode()).hexdigest()


def _hash_sidecar(branch_name: str) -> Path:
    # A sibling of the worktree, never inside it — so it's never at risk of being
    # committed/pushed, and survives independently of whatever's in the worktree.
    return WORKTREES_DIR / (branch_name.replace("/", "--") + ".mapping-hash")


def find_stale_worktree(erp_name: str, mapping: list[dict]) -> tuple[Path, str] | None:
    """A worktree from a previous run that got as far as a commit but never got
    pushed (push or PR creation failed afterward, e.g. the GitHub token permission
    issue we hit live) — reusing it means skipping run_coding_agent entirely, the
    slow and expensive step. Only reused when it was built from this EXACT mapping
    (hash-compared): if the mapping has since changed (a human corrected it), the
    old content would be wrong to push silently, so a mismatch is treated as not
    reusable — left alone, not force-overwritten — and a fresh run proceeds instead.
    """
    agent_dir = WORKTREES_DIR / "agent"
    if not agent_dir.exists():
        return None
    slug = erp_name.lower().replace(" ", "-")
    wanted_hash = _mapping_hash(mapping)
    candidates: list[tuple[Path, str]] = []
    for path in agent_dir.glob(f"erp-{slug}-*"):
        if not path.is_dir():
            continue
        branch_name = f"agent/{path.name}"
        hash_file = _hash_sidecar(branch_name)
        if not hash_file.exists() or hash_file.read_text().strip() != wanted_hash:
            continue  # different or unrecorded mapping — don't touch it either way
        status = subprocess.run(
            ["git", "status", "--short"], cwd=path, capture_output=True, text=True
        )
        if status.returncode != 0 or status.stdout.strip():
            continue  # missing, broken, or dirty — not safe to push as-is
        ahead = subprocess.run(
            ["git", "rev-list", "--count", "main..HEAD"], cwd=path, capture_output=True, text=True
        )
        if ahead.returncode != 0 or int(ahead.stdout.strip() or 0) == 0:
            continue  # nothing committed beyond main — not actually finished
        candidates.append((path, branch_name))
    if not candidates:
        return None
    return max(candidates, key=lambda pair: pair[0].stat().st_mtime)


def run_coding_agent(worktree_path: Path, prompt: str) -> str:
    # On this network, a corporate proxy rewrites Bedrock's streaming response
    # content-type, which Claude Code otherwise rejects outright (confirmed via a
    # direct test — same class of TLS interception seen earlier with pip). Set
    # explicitly here rather than only documented in .env.example, since a var only
    # in the example file doesn't reliably make it into anyone's actual .env.
    env = {**os.environ, "CLAUDE_CODE_DISABLE_BEDROCK_CONTENT_TYPE_GUARD": "1"}
    # Mirrors the deny-list from the earlier Kiro-agent design for this same task —
    # the agent never needs to commit/push itself (we do that in a separate step
    # with a scoped, redacted-on-failure token) or touch package managers/containers.
    # `git diff`/`git status` etc. stay allowed since reviewing its own changes is
    # normal, harmless agent behavior; only the mutating/escalating commands are denied.
    disallowed = [
        "Bash(git commit*)",
        "Bash(git push*)",
        "Bash(git add*)",
        "Bash(rm -rf*)",
        "Bash(sudo*)",
        "Bash(pip install*)",
        "Bash(docker*)",
    ]
    result = subprocess.run(
        [
            "claude",
            "--bare",
            "--model",
            CODING_AGENT_MODEL,
            "-p",
            prompt,
            "--permission-mode",
            "acceptEdits",
            "--disallowedTools",
            *disallowed,
        ],
        cwd=worktree_path,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=AGENT_TIMEOUT_SECONDS,
        env=env,
    )
    if result.returncode != 0:
        raise AgentRunError(
            f"claude CLI failed (exit {result.returncode}):\n{result.stdout}\n{result.stderr}"
        )
    return result.stdout


def run_tests(worktree_path: Path) -> str:
    result = subprocess.run(
        ["python", "-m", "pytest", "-q", "src/modules/integration/erp"],
        cwd=worktree_path,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=600,
    )
    if result.returncode != 0:
        raise AgentRunError(f"tests failed:\n{result.stdout}\n{result.stderr}")
    return result.stdout


def push_branch(worktree_path: Path, branch_name: str) -> None:
    _run(
        ["git", *_auth_header_args(), "push", "-u", "origin", branch_name],
        cwd=worktree_path,
        timeout=120,
    )


def commit_and_push(worktree_path: Path, branch_name: str, message: str) -> None:
    _run(["git", "add", "-A"], cwd=worktree_path, timeout=30)
    _run(["git", "commit", "-m", message], cwd=worktree_path, timeout=30)
    push_branch(worktree_path, branch_name)


def _repo_slug() -> str:
    """ "owner/repo" from TARGET_REPO_URL, e.g. "octocat/hello-world" from
    https://github.com/octocat/hello-world.git — used for the GitHub REST API."""
    path = urlparse(TARGET_REPO_URL).path.strip("/")
    return path[: -len(".git")] if path.endswith(".git") else path


def create_pull_request(branch_name: str, title: str, body: str) -> str:
    """Via GitHub's REST API directly, not the `gh` CLI — confirmed live that `gh`
    isn't installed on this machine at all (a FileNotFoundError, not a permission
    error), and this uses the exact same GITHUB_TOKEN already proven to push/read
    successfully. Also one less host dependency for a future container image."""
    url = f"https://api.github.com/repos/{_repo_slug()}/pulls"
    payload = json.dumps(
        {"title": title, "body": body, "head": branch_name, "base": "main"}
    ).encode()
    req = urllib.request.Request(
        url,
        data=payload,
        method="POST",
        headers={
            "Authorization": f"Bearer {GITHUB_TOKEN}",
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode())
        return data["html_url"]
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")
        raise AgentRunError(f"GitHub PR creation failed (HTTP {e.code}): {detail}")


def run_approval(erp_name: str, mapping: list[dict]) -> dict:
    with _step("find_stale_worktree"):
        stale = find_stale_worktree(erp_name, mapping)

    if stale:
        worktree_path, branch_name = stale
        log.info(
            "resuming stale completed worktree for erp=%s branch=%s — skipping run_coding_agent",
            erp_name,
            branch_name,
        )
        with _step("is_erp_registered"):
            already_registered = is_erp_registered(worktree_path, erp_name)
        verb = "Update" if already_registered else "Add"
        with _step("run_tests (re-check before pushing stale work)"):
            test_output = run_tests(worktree_path)
        with _step("push_branch"):
            push_branch(worktree_path, branch_name)
    else:
        slug = erp_name.lower().replace(" ", "-")
        branch_name = f"agent/erp-{slug}-{uuid.uuid4().hex[:8]}"
        log.info(
            "run_approval starting: erp=%s branch=%s model=%s",
            erp_name,
            branch_name,
            CODING_AGENT_MODEL,
        )

        with _step(f"create_worktree({branch_name})"):
            worktree_path = create_worktree(branch_name)
        _hash_sidecar(branch_name).write_text(_mapping_hash(mapping))

        with _step("is_erp_registered"):
            already_registered = is_erp_registered(worktree_path, erp_name)
        verb = "Update" if already_registered else "Add"
        log.info("already_registered=%s -> %s", already_registered, verb)

        prompt = build_task_prompt(erp_name, mapping, already_registered)
        with _step("run_coding_agent (claude CLI)"):
            run_coding_agent(worktree_path, prompt)
        with _step("run_tests"):
            test_output = run_tests(worktree_path)
        with _step("commit_and_push"):
            commit_and_push(
                worktree_path,
                branch_name,
                f"{verb} {erp_name} ERP {'mapping' if already_registered else 'adapter'}",
            )

    mapping_rows = "\n".join(
        f"| {m['erp_field']} | {m['canonical_field']} | {m['confidence']}% |" for m in mapping
    )
    summary = (
        f"Updates the existing {erp_name} ERP adapter's field mapping to match an approved "
        f"mapping, reviewed by a human before this PR was opened."
        if already_registered
        else f"Adds the {erp_name} ERP adapter, generated from an approved field mapping and "
        f"reviewed by a human before this PR was opened."
    )
    pr_body = f"""## Summary
{summary}

## AI mapping confidence
| ERP field | Canonical field | Confidence |
|---|---|---:|
{mapping_rows}

## Validation
```
{test_output[-2000:]}
```
"""
    with _step("create_pull_request"):
        pr_url = create_pull_request(
            branch_name,
            f"{verb} {erp_name} ERP {'mapping' if already_registered else 'adapter'}",
            pr_body,
        )
    log.info("run_approval done: erp=%s branch=%s pr=%s", erp_name, branch_name, pr_url)

    # Best-effort, never lets a cleanup problem undo a successful PR: the run is
    # done the moment the PR exists, regardless of whether tidying up afterward works.
    try:
        remove_worktree(worktree_path, branch_name)
        hash_file = _hash_sidecar(branch_name)
        if hash_file.exists():
            hash_file.unlink()
        log.info("cleaned up worktree: %s", worktree_path)
    except Exception as e:
        log.warning("worktree cleanup failed (non-fatal, PR already exists): %s", e)

    return {
        "branch": branch_name,
        "pr_url": pr_url,
        "already_registered": already_registered,
        "resumed_from_stale_worktree": stale is not None,
    }
