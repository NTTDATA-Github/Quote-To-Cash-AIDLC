"""Mapping-proposer domain model — plain dataclasses, framework-free.

A `CanonicalSchema` is the operator's target field list (a name + a CSV of
`field,description` rows). A `MappingJob` is one proposal run: the ERP samples go in, the
LLM-proposed `MappingEntry` rows come out, and — once a human approves — an adapter run is
launched on `erp-agent-service` and its id remembered on `adapter_run_id`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum


def _utcnow() -> datetime:
    return datetime.now(UTC)


class MappingStatus(str, Enum):
    PENDING = "PENDING"  # enqueued, not yet claimed by the worker
    PROCESSING = "PROCESSING"  # claimed, LLM call in flight
    DONE = "DONE"  # a mapping was proposed (possibly empty — nothing matched)
    FAILED = "FAILED"  # the LLM call errored after retries


@dataclass(frozen=True)
class MappingEntry:
    """One proposed mapping of an ERP field onto a canonical field. `confidence` is a
    0-100 integer the prompt calibrates strictly — treat anything below ~95 as something
    to check by hand (see `domain/proposal.py`)."""

    erp_field: str
    canonical_field: str
    sample_data: str
    confidence: int


@dataclass(frozen=True)
class CanonicalSchema:
    """A named target field list, reusable across many jobs. `csv_text` is the raw
    `field,description` CSV; parsing lives in `domain/proposal.py` so this stays data."""

    name: str
    csv_text: str
    created_at: datetime = field(default_factory=_utcnow)


@dataclass(frozen=True)
class AdapterRunResult:
    """A snapshot of the `erp-agent-service` run that implements an approved mapping.
    `status` mirrors that service's job states (PENDING/PROCESSING/DONE/FAILED)."""

    status: str
    branch: str | None = None
    pr_url: str | None = None
    error: str | None = None


@dataclass
class MappingJob:
    """One proposal run. `canonical_fields_csv` is resolved at submit time (either copied
    from a registered schema or passed inline) so the job is self-contained — reprocessing
    never depends on a schema that may have changed since. `sample_exports` maps each
    uploaded filename to its already-truncated sample text."""

    job_id: str
    erp_name: str
    status: MappingStatus
    canonical_fields_csv: str
    sample_exports: dict[str, str]
    schema_name: str | None = None
    result: list[MappingEntry] | None = None
    error: str | None = None
    adapter_run_id: str | None = None
    created_at: datetime = field(default_factory=_utcnow)

    @property
    def is_terminal(self) -> bool:
        return self.status in (MappingStatus.DONE, MappingStatus.FAILED)
