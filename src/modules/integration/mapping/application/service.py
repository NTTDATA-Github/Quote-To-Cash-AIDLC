"""MappingService — register canonical schemas, submit/read proposal jobs, and approve a
reviewed mapping (which launches an adapter run on `erp-agent-service`).

Deliberately thin: no LLM call here (that's the worker, via `MappingProposer`), no HTTP
here (that's the `AdapterRunLauncher` port). Operator-only; the GraphQL layer gates it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from src.shared.types import generate_id

from ..domain.errors import (
    CanonicalSchemaNotFound,
    EmptyCanonicalSchema,
    MappingJobNotFound,
    MappingNotReady,
    NoCanonicalFields,
)
from ..domain.models import CanonicalSchema, MappingJob, MappingStatus
from ..domain.proposal import extract_sample, parse_fields

if TYPE_CHECKING:
    from ..domain.models import AdapterRunResult
    from .ports import AdapterRunLauncher, CanonicalSchemaRepository, MappingJobRepository


class MappingService:
    def __init__(
        self,
        jobs: MappingJobRepository,
        schemas: CanonicalSchemaRepository,
        launcher: AdapterRunLauncher,
    ) -> None:
        self._jobs = jobs
        self._schemas = schemas
        self._launcher = launcher

    # --- canonical schemas ---
    def register_schema(self, name: str, csv_text: str) -> CanonicalSchema:
        if not parse_fields(csv_text):
            raise EmptyCanonicalSchema("no fields found — expected a CSV with a 'field' column")
        schema = CanonicalSchema(name=name, csv_text=csv_text)
        self._schemas.add(schema)
        return schema

    def list_schemas(self) -> list[str]:
        return self._schemas.list_names()

    def field_count(self, name: str) -> int:
        schema = self._schemas.get(name)
        return 0 if schema is None else len(parse_fields(schema.csv_text))

    # --- jobs ---
    def submit_job(
        self,
        *,
        erp_name: str,
        sample_files: dict[str, str],
        schema_name: str | None = None,
        canonical_fields_csv: str | None = None,
    ) -> MappingJob:
        """`sample_files` maps each uploaded filename to its RAW text; each is truncated to
        a sample here. The canonical field list comes from EITHER a registered
        `schema_name` OR an inline `canonical_fields_csv` — exactly one."""
        if schema_name:
            schema = self._schemas.get(schema_name)
            if schema is None:
                raise CanonicalSchemaNotFound(schema_name)
            resolved_csv = schema.csv_text
        elif canonical_fields_csv:
            if not parse_fields(canonical_fields_csv):
                raise EmptyCanonicalSchema("inline canonical_fields_csv had no 'field' rows")
            resolved_csv = canonical_fields_csv
        else:
            raise NoCanonicalFields(
                "give either schema_name (a registered schema) or canonical_fields_csv"
            )

        if not sample_files:
            raise ValueError("at least one ERP sample export is required")

        samples = {name: extract_sample(name, text) for name, text in sample_files.items()}

        job = MappingJob(
            job_id=generate_id("map"),
            erp_name=erp_name,
            status=MappingStatus.PENDING,
            canonical_fields_csv=resolved_csv,
            sample_exports=samples,
            schema_name=schema_name,
        )
        self._jobs.add(job)
        return job

    def get_job(self, job_id: str) -> MappingJob | None:
        return self._jobs.get(job_id)

    # --- approve -> adapter run ---
    def approve(self, job_id: str) -> MappingJob:
        """Hand the reviewed mapping to the adapter-codegen service. The mapping is treated
        as ground truth there — review it before calling this."""
        job = self._jobs.get(job_id)
        if job is None:
            raise MappingJobNotFound(job_id)
        if job.status is not MappingStatus.DONE or job.result is None:
            raise MappingNotReady(f"job {job_id} is {job.status.value}, not DONE")
        run_id = self._launcher.launch(job.erp_name, job.result)
        job.adapter_run_id = run_id
        self._jobs.update(job)
        return job

    def get_adapter_run(self, job_id: str) -> AdapterRunResult | None:
        job = self._jobs.get(job_id)
        if job is None:
            raise MappingJobNotFound(job_id)
        if job.adapter_run_id is None:
            return None
        return self._launcher.get_run(job.adapter_run_id)
