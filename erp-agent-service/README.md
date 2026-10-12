# ERP adapter codegen agent

Given an approved ERP field mapping (from the portal's operator "ERP mapping" tab, or
anywhere else — this service doesn't care where it came from), implements the actual
adapter code, runs its tests, and opens a PR. A separate service from the mapping
proposer on purpose: the proposer is generic LLM-backed field matching; this service is
inherently tied to *this* repo, since its whole job is writing code into it, so it shells
out to `git`/`claude` on its host and can't be folded into the portal process.

## Code layout

```
service/
  app.py      FastAPI routes: POST /runs (submit), GET /runs/{id} (poll)
  jobs.py     SQLite-backed job queue — same enqueue/claim/finish shape as
              erp-mapping-service's, separate table
  agent.py    The orchestration: git worktree -> headless `claude` -> tests ->
              commit/push -> PR via GitHub's REST API (no `gh` CLI needed)
  worker.py   Polling loop: claims a run, calls agent.run_approval, saves the result
```

## Prerequisites (host, not pip)

This service shells out to `git` and `claude` rather than calling any LLM API
directly from Python, and talks to GitHub's REST API with stdlib `urllib` rather
than needing the `gh` CLI installed — `requirements.txt` is deliberately light:

- **`git`** — this service manages its own clone of `TARGET_REPO_URL` under
  `REPO_CACHE_DIR` (`agent.py`'s `ensure_repo()`: clones on first use, fetches +
  hard-resets to `origin/main` on every later run), then creates an isolated worktree
  + branch off that clone per run (`git worktree add`). It never assumes a checkout
  is already sitting on disk — that's what makes this portable to a plain container
  with nothing pre-existing, not just a dev machine with `erp-platform` already
  cloned next to it.
- **`claude`** (Claude Code CLI) — does the actual implementation, invoked headlessly
  (`claude --bare -p "<task>" --permission-mode acceptEdits`, with `--disallowedTools`
  blocking it from committing/pushing itself or running `rm -rf`/`sudo`/`pip
  install`/`docker` — it only needs to read and edit files and run the test suite).
  Configure its auth the same way you would interactively — see `.env.example` for
  the Bedrock env vars (`CLAUDE_CODE_USE_BEDROCK=1` + `AWS_BEARER_TOKEN_BEDROCK`,
  confirmed working against `us.anthropic.claude-sonnet-5`) or a direct
  `ANTHROPIC_API_KEY`.
- **`GITHUB_TOKEN`** (a PAT, `Contents: Read and write` + `Pull requests: Read and
  write` — see `.env.example`) — used for git clone/fetch/push (as a Basic-auth
  header, `<your-github-username>:<token>`, never written to disk) and for opening
  the PR via a direct `POST /repos/{owner}/{repo}/pulls` call. One token, both
  consumers. The username matters: `x-access-token` (a GitHub App convention) is
  NOT valid for a personal token and 403s on push even when the token's own
  permissions are fine — `agent.py` derives your actual username from
  `TARGET_REPO_URL` automatically.

Nothing here blocks a Dockerfile — a container just needs `git` and `claude`
installed plus a writable volume for `REPO_CACHE_DIR`/`WORKTREES_DIR`, not a
pre-baked checkout and not `gh`.

## Resuming after a failed run

If a run gets all the way through implementing + testing but fails on push or PR
creation (exactly what happened debugging this service against a real repo), the
worktree is left in place rather than discarded. The *next* `/runs` request for the
same ERP checks for one first (`agent.py`'s `find_stale_worktree`) — if it finds a
clean, committed worktree built from the **exact same mapping** (hash-compared, so a
corrected mapping never silently reuses stale code), it skips `run_coding_agent`
entirely and goes straight to re-testing + pushing. A worktree is only removed after
its PR is actually created; anything that fails stays around as a resume candidate.

## API

```
POST /runs   {"erp_name": "SAP", "mapping": [
                {"erp_field": "KUNNR", "canonical_field": "erp_customer_id",
                 "sample_data": "C1", "confidence": 97},
                ...
              ]}
             -> {"run_id": "...", "status": "PENDING"}

GET  /runs/{run_id} -> {"status": "DONE", "result": {
                          "branch": "agent/erp-sap-ab12cd34",
                          "pr_url": "https://github.com/.../pull/184",
                          "already_registered": false,
                          "resumed_from_stale_worktree": false
                        }}
```

`mapping` is whatever a human has already approved — this service treats it as
ground truth, not something to re-derive or second-guess (see `agent.py`'s task
prompt). It does NOT take raw ERP samples or canonical schemas; proposing the mapping is
the portal's job. The portal's operator API calls this service over HTTP when an operator
approves a mapping (`AGENT_SERVICE_URL`); nothing reseller-facing ever reaches it.

## Run it locally

```bash
pip install -r requirements.txt
cp .env.example .env   # fill in TARGET_REPO_URL and GITHUB_TOKEN
uvicorn service.app:app --reload --port 8002   # terminal 1
python -m service.worker                         # terminal 2
pytest -q
```

Only committed, pushed state is visible to a run — it clones from `TARGET_REPO_URL`
fresh, it doesn't see your local uncommitted changes or unpushed branches. Push the
branch you want the agent working from first.

A run creates `./worktrees/agent/<branch>/`. On success (PR created), it's removed
automatically. On failure, it's deliberately left in place — see "Resuming after a
failed run" above — so if you'd rather discard one than let a later run resume it,
remove it yourself (`git worktree remove --force <path>` from `REPO_CACHE_DIR`, then
`git branch -D <branch>`, then delete its `.mapping-hash` sidecar in `WORKTREES_DIR`).
