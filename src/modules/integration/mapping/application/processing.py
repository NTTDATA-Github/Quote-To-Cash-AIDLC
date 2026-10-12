"""Claim PENDING mapping jobs and run them through the LLM.

The split (API enqueues, this processes) keeps a slow or rate-limited LLM call off the
request path — the same reason the former standalone service had a separate worker. Driven
by the portal worker's `mapping` role in the postgres profile; called inline (with a
deterministic stub proposer) in the memory profile so local dev/tests work offline.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from ..domain.models import MappingStatus

if TYPE_CHECKING:
    from .ports import MappingJobRepository, MappingProposer

log = logging.getLogger("mapping-worker")


def process_pending_jobs(
    jobs: MappingJobRepository, proposer: MappingProposer, limit: int = 5
) -> int:
    """Process up to `limit` claimed jobs; return how many were claimed. Each job's outcome
    (DONE with a result, or FAILED with an error) is persisted independently, so one bad
    job never blocks the rest."""
    claimed = jobs.claim_pending(limit)
    for job in claimed:
        try:
            result = proposer.propose(job.erp_name, job.sample_exports, job.canonical_fields_csv)
            job.result = result
            job.error = None
            job.status = MappingStatus.DONE
            log.info("mapped job=%s erp=%s fields=%d", job.job_id, job.erp_name, len(result))
        except Exception as e:  # any provider/parse failure becomes a FAILED job, not a crash
            job.result = None
            job.error = f"{type(e).__name__}: {e}"
            job.status = MappingStatus.FAILED
            log.exception("mapping job=%s failed", job.job_id)
        jobs.update(job)
    return len(claimed)
