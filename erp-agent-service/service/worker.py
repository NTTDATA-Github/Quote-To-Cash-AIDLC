"""Polling worker: claims PENDING agent runs and turns an approved mapping into a PR
via agent.py.

Separate process from the API — an agent run spawns `claude` as a subprocess, runs
tests, and pushes/opens a PR, which can take minutes; it must never block the API.
"""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from . import agent, jobs  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("agent-worker")

POLL_SECONDS = float(os.environ.get("POLL_SECONDS", "5"))


def run_once() -> int:
    claimed = jobs.claim_pending()
    for run in claimed:
        try:
            mapping = json.loads(run["input_json"])["mapping"]
            result = agent.run_approval(run["erp_name"], mapping)
            jobs.finish(run["id"], result=result)
            log.info("run=%s erp=%s pr=%s", run["id"], run["erp_name"], result["pr_url"])
        except Exception as e:
            jobs.finish(run["id"], error=f"{type(e).__name__}: {e}")
            log.exception("run=%s failed", run["id"])
    return len(claimed)


def main() -> None:  # pragma: no cover - process entrypoint
    log.info("agent worker starting, polling every %ss", POLL_SECONDS)
    while True:
        if run_once() == 0:
            time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
