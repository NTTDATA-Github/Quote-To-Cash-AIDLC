"""Agent-orchestration API: given an approved ERP field mapping, implements the
adapter (via headless Claude Code) in an isolated git worktree, runs tests, and opens
a PR against the target repo.

Separate service from erp-mapping-service on purpose (see agent.py's docstring). The
UI calls both services as two independent backends — this one never sees uploaded
files, only the already-approved mapping JSON.
"""

from __future__ import annotations

import json
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from . import jobs  # noqa: E402

app = FastAPI(title="ERP adapter codegen agent")


class FieldMapping(BaseModel):
    erp_field: str
    canonical_field: str
    sample_data: str
    confidence: int


class RunRequest(BaseModel):
    erp_name: str
    mapping: list[FieldMapping]


@app.post("/runs")
def create_run(req: RunRequest):
    run_id = jobs.enqueue(req.erp_name, [m.model_dump() for m in req.mapping])
    return {"run_id": run_id, "status": "PENDING"}


@app.get("/runs/{run_id}")
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
