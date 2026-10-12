"""In-memory mapping infrastructure (tests + offline local dev).

The two repositories are dict-backed. `StubMappingProposer` and `StubAdapterRunLauncher`
stand in for the real LLM / `erp-agent-service` calls so the memory profile runs end to
end with no AWS and no network — deterministic, which is what the tests rely on.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from src.shared.types import generate_id

from ..domain.models import AdapterRunResult, MappingEntry, MappingStatus
from ..domain.proposal import valid_field_names

if TYPE_CHECKING:
    from ..domain.models import CanonicalSchema, MappingJob


class InMemoryCanonicalSchemaRepository:
    def __init__(self) -> None:
        self._by_name: dict[str, CanonicalSchema] = {}

    def add(self, schema: CanonicalSchema) -> None:
        self._by_name[schema.name] = schema

    def get(self, name: str) -> CanonicalSchema | None:
        return self._by_name.get(name)

    def list_names(self) -> list[str]:
        return sorted(self._by_name)


class InMemoryMappingJobRepository:
    def __init__(self) -> None:
        self._by_id: dict[str, MappingJob] = {}

    def add(self, job: MappingJob) -> None:
        self._by_id[job.job_id] = job

    def get(self, job_id: str) -> MappingJob | None:
        return self._by_id.get(job_id)

    def update(self, job: MappingJob) -> None:
        self._by_id[job.job_id] = job

    def list_recent(self, limit: int = 50) -> list[MappingJob]:
        jobs = sorted(self._by_id.values(), key=lambda job: job.created_at, reverse=True)
        return jobs[:limit]

    def claim_pending(self, limit: int = 5) -> list[MappingJob]:
        claimed: list[MappingJob] = []
        for job in self._by_id.values():
            if job.status is MappingStatus.PENDING:
                job.status = MappingStatus.PROCESSING
                claimed.append(job)
                if len(claimed) >= limit:
                    break
        return claimed


class StubMappingProposer:
    """Deterministic, offline stand-in for the LLM. Maps an ERP field to a canonical field
    only on an exact case-insensitive name match — enough for local dev and tests to see a
    non-empty result without inventing anything. The real proposer is Bedrock-backed."""

    def propose(
        self, erp_name: str, sample_exports: dict[str, str], canonical_fields_csv: str
    ) -> list[MappingEntry]:
        valid = valid_field_names(canonical_fields_csv)
        by_lower = {name.lower(): name for name in valid}
        entries: list[MappingEntry] = []
        seen: set[str] = set()
        for text in sample_exports.values():
            for raw in _header_fields(text):
                key = raw.strip().lower()
                if key in by_lower and key not in seen:
                    seen.add(key)
                    entries.append(
                        MappingEntry(
                            erp_field=raw.strip(),
                            canonical_field=by_lower[key],
                            sample_data="",
                            confidence=50,
                        )
                    )
        return entries


def _header_fields(sample_text: str) -> list[str]:
    """Best-effort column names from a sample: the first CSV line's comma-split cells, or
    the keys of the first object in a JSON array."""
    if sample_text.lstrip().startswith("["):
        try:
            data = json.loads(sample_text)
        except json.JSONDecodeError:
            return []
        if data and isinstance(data[0], dict):
            return [str(k) for k in data[0]]
        return []
    lines = sample_text.splitlines()
    return lines[0].split(",") if lines else []


class StubAdapterRunLauncher:
    """Offline stand-in for `erp-agent-service`. Pretends a run completed instantly."""

    def __init__(self) -> None:
        self._runs: dict[str, str] = {}

    def launch(self, erp_name: str, mapping: list[MappingEntry]) -> str:
        run_id = generate_id("run")
        self._runs[run_id] = erp_name
        return run_id

    def get_run(self, run_id: str) -> AdapterRunResult:
        erp_name = self._runs.get(run_id, "erp")
        slug = erp_name.lower().replace(" ", "-")
        return AdapterRunResult(
            status="DONE",
            branch=f"agent/{slug}-stub",
            pr_url="https://example.invalid/pull/0",
            error=None,
        )
