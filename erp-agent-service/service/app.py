"""Agent-orchestration API: given an approved ERP field mapping, implements the
adapter (via headless Claude Code) in an isolated git worktree, runs tests, and opens
a PR against the target repo.

Separate service from erp-mapping-service on purpose (see agent.py's docstring). The
UI calls both services as two independent backends — this one never sees uploaded
files, only the already-approved mapping JSON.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, field_validator

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from . import jobs  # noqa: E402

app = FastAPI(title="ERP adapter codegen agent")

# Only letters/digits/space/()._- : matches real instance labels ("Local Odoo (dev)")
# while blocking "/" and "..", which would otherwise let erp_name escape WORKTREES_DIR
# through the branch name built from it (see agent.py's create_worktree/find_stale_worktree).
_ERP_NAME_RE = re.compile(r"^[A-Za-z0-9 _.()-]{1,80}$")


def require_token(authorization: str | None = Header(default=None)) -> None:
    """This service holds a GitHub token with repo write access and will run a coding
    agent on request - it must never be reachable by anyone who merely has network
    access to its port. AGENT_API_TOKEN unset is a refusal, not an open door."""
    expected = os.environ.get("AGENT_API_TOKEN", "").strip()
    if not expected:
        raise HTTPException(
            500, "AGENT_API_TOKEN is not configured - refusing unauthenticated runs"
        )
    if authorization != f"Bearer {expected}":
        raise HTTPException(401, "invalid or missing bearer token")


class FieldMapping(BaseModel):
    erp_field: str
    canonical_field: str
    sample_data: str
    confidence: int


class RunRequest(BaseModel):
    erp_name: str
    mapping: list[FieldMapping]

    @field_validator("erp_name")
    @classmethod
    def _valid_erp_name(cls, value: str) -> str:
        if not _ERP_NAME_RE.match(value):
            raise ValueError("erp_name must be 1-80 chars of letters, digits, space, ()._-")
        return value


@app.post("/runs", dependencies=[Depends(require_token)])
def create_run(req: RunRequest):
    run_id = jobs.enqueue(req.erp_name, [m.model_dump() for m in req.mapping])
    return {"run_id": run_id, "status": "PENDING"}


@app.get("/runs/{run_id}", dependencies=[Depends(require_token)])
def get_run(run_id: str):
    run = jobs.get(run_id)
    if not run:
        raise HTTPException(404, "run not found")
    out = {"run_id": run["id"], "erp_name": run["erp_name"], "status": run["status"]}
    if run["status"] == "DONE":
        out["result"] = json.loads(run["result_json"])
    if run["status"] == "FAILED":
        out["error"] = run["error"]
    return out


@app.get("/livez")
def livez():
    return {"ok": True}
