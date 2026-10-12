"""Ports the mapping module depends on (implemented by infrastructure).

Two repositories (the canonical schema registry and the job store), the `MappingProposer`
(the LLM call — kept behind a port so the domain/application layers stay framework-free
and tests inject a deterministic stub), and the `AdapterRunLauncher` (the HTTP hand-off to
`erp-agent-service`, likewise a port so nothing here imports httpx or knows that service's
URL).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from ..domain.models import AdapterRunResult, CanonicalSchema, MappingEntry, MappingJob


class CanonicalSchemaRepository(Protocol):
    def add(self, schema: CanonicalSchema) -> None: ...
    def get(self, name: str) -> CanonicalSchema | None: ...
    def list_names(self) -> list[str]: ...


class MappingJobRepository(Protocol):
    def add(self, job: MappingJob) -> None: ...
    def get(self, job_id: str) -> MappingJob | None: ...
    def update(self, job: MappingJob) -> None: ...
    def claim_pending(self, limit: int = 5) -> list[MappingJob]:
        """Atomically mark up to `limit` PENDING jobs PROCESSING and return them."""
        ...


class LlmClient(Protocol):
    """A minimal text-in/text-out LLM call. The concrete client (Bedrock) lives in the
    shared kernel — boto3 is not allowed inside `src.modules` — and is injected here."""

    def ask(self, system: str, user: str) -> str: ...


class MappingProposer(Protocol):
    def propose(
        self, erp_name: str, sample_exports: dict[str, str], canonical_fields_csv: str
    ) -> list[MappingEntry]:
        """Call the LLM and return only genuine mappings (see `domain/proposal.py`).
        Raises on an unrecoverable provider/parse error after its own retries."""
        ...


class AdapterRunLauncher(Protocol):
    def launch(self, erp_name: str, mapping: list[MappingEntry]) -> str:
        """Hand an approved mapping to the adapter-codegen service; return its run id."""
        ...

    def get_run(self, run_id: str) -> AdapterRunResult: ...
