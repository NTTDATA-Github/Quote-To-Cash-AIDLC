"""Job queue for agent runs: the API enqueues (an approved mapping), the worker
claims and processes it (via agent.py), turning it into a PR. Same shape as
erp-mapping-service/service/jobs.py — a separate service, a separate job table.
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import UTC, datetime

from sqlalchemy import Column, DateTime, MetaData, String, Table, Text, create_engine, select
from sqlalchemy.orm import sessionmaker

DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///./agent_runs.db")

_metadata = MetaData()
agent_runs = Table(
    "agent_runs",
    _metadata,
    Column("id", String, primary_key=True),
    Column("erp_name", String, nullable=False),
    Column("status", String, nullable=False),  # PENDING | PROCESSING | DONE | FAILED
    Column("input_json", Text, nullable=False),  # {"mapping": [...]}
    Column("result_json", Text),  # {"branch":..., "pr_url":...}
    Column("error", Text),
    Column("created_at", DateTime, nullable=False),
)

_engine = create_engine(DATABASE_URL, future=True)
_metadata.create_all(_engine)
Session = sessionmaker(bind=_engine, future=True)


def enqueue(erp_name: str, mapping: list[dict]) -> str:
    run_id = str(uuid.uuid4())
    with Session() as s:
        s.execute(
            agent_runs.insert().values(
                id=run_id,
                erp_name=erp_name,
                status="PENDING",
                input_json=json.dumps({"mapping": mapping}),
                created_at=datetime.now(UTC),
            )
        )
        s.commit()
    return run_id


def get(run_id: str) -> dict | None:
    with Session() as s:
        row = s.execute(select(agent_runs).where(agent_runs.c.id == run_id)).mappings().first()
        return dict(row) if row else None


def claim_pending(limit: int = 1) -> list[dict]:
    """ponytail: limit=1 by default — an agent run holds a git worktree and spawns a
    real subprocess for minutes at a time; don't run several concurrently until that's
    actually needed. Also no SELECT...FOR UPDATE SKIP LOCKED, same caveat as
    erp-mapping-service/service/jobs.py."""
    with Session() as s:
        rows = [
            dict(r)
            for r in s.execute(
                select(agent_runs).where(agent_runs.c.status == "PENDING").limit(limit)
            ).mappings()
        ]
        if rows:
            ids = [r["id"] for r in rows]
            s.execute(
                agent_runs.update().where(agent_runs.c.id.in_(ids)).values(status="PROCESSING")
            )
            s.commit()
            for r in rows:
                r["status"] = "PROCESSING"
        return rows


def finish(run_id: str, *, result: dict | None = None, error: str | None = None) -> None:
    with Session() as s:
        s.execute(
            agent_runs.update()
            .where(agent_runs.c.id == run_id)
            .values(
                status="FAILED" if error else "DONE",
                result_json=json.dumps(result) if result is not None else None,
                error=error,
            )
        )
        s.commit()
