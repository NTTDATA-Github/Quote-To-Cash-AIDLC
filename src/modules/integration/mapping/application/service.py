"""MappingService — register canonical schemas, submit/read proposal jobs, and approve a
reviewed mapping (which launches an adapter run on `erp-agent-service`).

Deliberately thin: no LLM call here (that's the worker, via `MappingProposer`), no HTTP
to the ERP here either (that's the `ErpProbe` port) or to the codegen service (the
`AdapterRunLauncher` port). Operator-only; the GraphQL layer gates it.

ADR-0021/0022: every job is submitted *for* an existing `ErpConnection` (never a
free-typed ERP name) — its `base_url`/`credentials`/`secret_ref`/`auth_type` are read
from that connection, never retyped. Submission is rejected for a connection whose
`erp_type` already has a working adapter, or already has a pending/approved job for that
type (`eligible_connections`/`_ensure_eligible` — both checks, neither alone sufficient,
see ADR-0022).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from src.shared.erp_auth import AuthConfig, AuthType
from src.shared.types import ConnectionId, generate_id

from ..domain.errors import (
    CanonicalSchemaNotFound,
    ConnectionNotFound,
    EmptyCanonicalSchema,
    ErpTypeNotEligible,
    MappingJobNotFound,
    MappingNotReady,
    NoCanonicalFields,
    ProbeFailed,
)
from ..domain.models import CanonicalSchema, MappingJob, MappingStatus
from ..domain.proposal import extract_sample, parse_fields

if TYPE_CHECKING:
    from collections.abc import Callable

    from src.modules.reference.connections.domain.models import ErpConnection
    from src.shared.erp_probe import ErpProbe, ProbeSample, SampleRequestSpec
    from src.shared.secrets import SecretStore

    from ..domain.models import AdapterRunResult
    from .ports import (
        AdapterRunLauncher,
        CanonicalSchemaRepository,
        ConnectionRepository,
        MappingJobRepository,
    )

# A blocking job can be arbitrarily old; the dedupe scan (ADR-0022) needs all of them,
# not the small page the UI's job list shows.
_DEDUPE_SCAN_LIMIT = 10_000

# Non-terminal, or terminal-but-approved — either means "already spoken for."
_BLOCKING_STATUSES = (MappingStatus.PENDING, MappingStatus.PROCESSING)

# Onboarded through their own dedicated flow (see docs/netsuite-registration-guide.md),
# not the generic LLM mapper — deliberately separate from `has_adapter`, which must keep
# meaning "does real delivery code exist" and nothing else. Without this, blocking
# NetSuite here would piggyback on the has_adapter check and misreport the reason as
# "already has a working adapter."
_MAPPER_BLOCKED_ERP_TYPES = frozenset({"NETSUITE"})


class MappingService:
    def __init__(
        self,
        jobs: MappingJobRepository,
        schemas: CanonicalSchemaRepository,
        launcher: AdapterRunLauncher,
        probe: ErpProbe,
        secrets: SecretStore,
        connections: ConnectionRepository,
        has_adapter: Callable[[str], bool],
    ) -> None:
        self._jobs = jobs
        self._schemas = schemas
        self._launcher = launcher
        self._probe = probe
        self._secrets = secrets
        self._connections = connections
        self._has_adapter = has_adapter

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

    # --- ADR-0022: per-erp_type dedupe ---
    def _jobs_for_erp_type(
        self, erp_type: str, *, exclude_job_id: str | None = None
    ) -> list[MappingJob]:
        found: list[MappingJob] = []
        for job in self._jobs.list_recent(_DEDUPE_SCAN_LIMIT):
            if job.connection_id is None or job.job_id == exclude_job_id:
                continue
            connection = self._connections.get(ConnectionId(job.connection_id))
            if connection is not None and connection.erp_type == erp_type:
                found.append(job)
        return found

    def _ensure_eligible(self, connection: ErpConnection) -> None:
        """The *submit*-time gate: also blocks on a merely-PENDING/PROCESSING/
        DONE-unapproved sibling, which `_ensure_not_already_approved` doesn't — avoiding
        wasted duplicate LLM-proposal runs, not just duplicate code generation."""
        if self._has_adapter(connection.erp_type):
            raise ErpTypeNotEligible(
                f"'{connection.erp_type}' already has a working adapter — mapping it "
                "again would generate a redundant one"
            )
        for job in self._jobs_for_erp_type(connection.erp_type):
            blocked = job.status in _BLOCKING_STATUSES or (
                job.status is MappingStatus.DONE and job.adapter_run_id is not None
            )
            if blocked:
                raise ErpTypeNotEligible(
                    f"'{connection.erp_type}' already has mapping job {job.job_id} "
                    f"({job.status.value}) — wait for it or review it instead"
                )

    def _ensure_not_already_approved(self, connection: ErpConnection, job_id: str) -> None:
        """The *approve*-time gate: two jobs for the same `erp_type` can both reach DONE
        unapproved before either is reviewed (the submit-time gate doesn't block a
        DONE-unapproved sibling, by design — the operator might reject one and keep the
        other). This is the actual point code generation happens, so it's checked again
        here, independently — approving a second job for an erp_type already approved via
        another job is exactly the regression ADR-0022 exists to prevent."""
        if self._has_adapter(connection.erp_type):
            raise ErpTypeNotEligible(
                f"'{connection.erp_type}' already has a working adapter — approving this "
                "would generate a redundant one"
            )
        for job in self._jobs_for_erp_type(connection.erp_type, exclude_job_id=job_id):
            if job.status is MappingStatus.DONE and job.adapter_run_id is not None:
                raise ErpTypeNotEligible(
                    f"'{connection.erp_type}' was already approved via job {job.job_id} — "
                    "approving this one too would generate a second, redundant adapter"
                )

    def _has_blocking_job(self, erp_type: str) -> bool:
        return any(
            job.status in _BLOCKING_STATUSES
            or (job.status is MappingStatus.DONE and job.adapter_run_id is not None)
            for job in self._jobs_for_erp_type(erp_type)
        )

    def connection_mapping_status(self, connection: ErpConnection) -> str:
        """The UI-facing state `hasAdapter` alone can't tell apart: a connection whose
        type has no adapter yet is not automatically "needs mapping" — a job for that
        type may already be running or already approved (ADR-0022 blocks a second one
        either way), in which case there's genuinely nothing to do on the Mapping page
        yet. One of: `ADAPTER_READY`, `MAPPING_IN_PROGRESS`, `AWAITING_ADAPTER`
        (approved, waiting for the generated code to actually land), `NEEDS_MAPPING`
        (the only state `eligible_connections`/`mappableConnections` would offer)."""
        if self._has_adapter(connection.erp_type):
            return "ADAPTER_READY"
        for job in self._jobs_for_erp_type(connection.erp_type):
            if job.status in _BLOCKING_STATUSES:
                return "MAPPING_IN_PROGRESS"
            if job.status is MappingStatus.DONE and job.adapter_run_id is not None:
                return "AWAITING_ADAPTER"
        return "NEEDS_MAPPING"

    def eligible_connections(self) -> list[ErpConnection]:
        """What the Mapping page's connection picker offers — connections whose
        `erp_type` has no adapter yet and no job already in flight/approved."""
        eligible: list[ErpConnection] = []
        for connection in self._connections.list_all():
            if self._has_adapter(connection.erp_type):
                continue
            if self._has_blocking_job(connection.erp_type):
                continue
            eligible.append(connection)
        return eligible

    def _get_eligible_connection(self, connection_id: str) -> ErpConnection:
        connection = self._connections.get(ConnectionId(connection_id))
        if connection is None:
            raise ConnectionNotFound(connection_id)
        self._ensure_eligible(connection)
        return connection

    # Public alias: `SampleRequestSuggestionService` needs the same connection + the same
    # eligibility gate (suggesting sample requests for a connection that's already mapped
    # makes no sense) but lives outside this class so an LLM call never sneaks in here.
    get_eligible_connection = _get_eligible_connection

    # --- jobs ---
    def resolve_canonical_fields(
        self, schema_name: str | None, canonical_fields_csv: str | None
    ) -> str:
        """Public because `SampleRequestSuggestionService` needs the same resolution
        (a registered schema OR an inline CSV, exactly one) before it can ground its
        suggestions in the fields actually being looked for."""
        if schema_name:
            schema = self._schemas.get(schema_name)
            if schema is None:
                raise CanonicalSchemaNotFound(schema_name)
            return schema.csv_text
        if canonical_fields_csv:
            if not parse_fields(canonical_fields_csv):
                raise EmptyCanonicalSchema("inline canonical_fields_csv had no 'field' rows")
            return canonical_fields_csv
        raise NoCanonicalFields(
            "give either schema_name (a registered schema) or canonical_fields_csv"
        )

    def submit_job(
        self,
        *,
        connection_id: str,
        sample_files: dict[str, str],
        schema_name: str | None = None,
        canonical_fields_csv: str | None = None,
    ) -> MappingJob:
        """`sample_files` maps each uploaded filename to its RAW text; each is truncated to
        a sample here. The canonical field list comes from EITHER a registered
        `schema_name` OR an inline `canonical_fields_csv` — exactly one. Manual upload
        stays available regardless of the connection's `auth_type` (ADR-0021) — the one
        path that works for any ERP, however exotic its auth."""
        connection = self._get_eligible_connection(connection_id)
        resolved_csv = self.resolve_canonical_fields(schema_name, canonical_fields_csv)

        if not sample_files:
            raise ValueError("at least one ERP sample export is required")

        samples = {name: extract_sample(name, text) for name, text in sample_files.items()}

        job = MappingJob(
            job_id=generate_id("map"),
            erp_name=connection.instance_label,
            status=MappingStatus.PENDING,
            canonical_fields_csv=resolved_csv,
            sample_exports=samples,
            schema_name=schema_name,
            connection_id=connection_id,
        )
        self._jobs.add(job)
        return job

    # --- onboarding probe (fetch samples live instead of a manual file upload) ---
    def probe_samples(
        self, *, connection_id: str, requests: list[SampleRequestSpec]
    ) -> list[ProbeSample]:
        """Fires each `SampleRequestSpec` against the connection's `base_url`, using its
        already-stored `auth_type`/`credentials`/`secret_ref` (ADR-0021) — nothing is
        retyped. A preview the operator can review before committing to a mapping job."""
        connection = self._get_eligible_connection(connection_id)
        auth = AuthConfig(
            auth_type=AuthType(connection.auth_type), params=dict(connection.credentials)
        )
        return self._probe.fetch_samples(
            base_url=connection.base_url,
            auth=auth,
            secret_ref=connection.secret_ref,
            requests=requests,
        )

    def submit_job_from_probe(
        self,
        *,
        connection_id: str,
        requests: list[SampleRequestSpec],
        schema_name: str | None = None,
        canonical_fields_csv: str | None = None,
    ) -> MappingJob:
        """Probes live, then calls `submit_job` with the fetched samples — same job shape
        and downstream flow as a manually-uploaded one. Raises `ProbeFailed` if any
        request failed, since a partial/missing sample set would silently bias the LLM's
        proposal rather than visibly block it."""
        samples = self.probe_samples(connection_id=connection_id, requests=requests)
        errors = [s for s in samples if s.error]
        if errors:
            detail = "; ".join(f"{s.label}: {s.error}" for s in errors)
            raise ProbeFailed(f"{len(errors)} of {len(samples)} sample request(s) failed: {detail}")
        sample_files = {s.label: s.text for s in samples if s.text is not None}
        return self.submit_job(
            connection_id=connection_id,
            sample_files=sample_files,
            schema_name=schema_name,
            canonical_fields_csv=canonical_fields_csv,
        )

    def get_job(self, job_id: str) -> MappingJob | None:
        return self._jobs.get(job_id)

    def list_jobs(self, limit: int = 50) -> list[MappingJob]:
        return self._jobs.list_recent(limit)

    # --- approve -> adapter run ---
    def approve(self, job_id: str) -> MappingJob:
        """Hand the reviewed mapping to the adapter-codegen service. The mapping is treated
        as ground truth there — review it before calling this."""
        job = self._jobs.get(job_id)
        if job is None:
            raise MappingJobNotFound(job_id)
        if job.status is not MappingStatus.DONE or job.result is None:
            raise MappingNotReady(f"job {job_id} is {job.status.value}, not DONE")
        if job.connection_id is not None:
            connection = self._connections.get(ConnectionId(job.connection_id))
            if connection is not None:
                self._ensure_not_already_approved(connection, job_id)
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
