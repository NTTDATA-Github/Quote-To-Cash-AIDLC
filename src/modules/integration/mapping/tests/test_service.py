from __future__ import annotations

from datetime import UTC, datetime

import pytest

from src.modules.integration.mapping.application.processing import process_pending_jobs
from src.modules.integration.mapping.application.service import MappingService
from src.modules.integration.mapping.domain.errors import (
    CanonicalSchemaNotFound,
    EmptyCanonicalSchema,
    MappingNotReady,
    NoCanonicalFields,
)
from src.modules.integration.mapping.domain.models import MappingStatus
from src.modules.integration.mapping.infrastructure.memory import (
    InMemoryCanonicalSchemaRepository,
    InMemoryMappingJobRepository,
    StubAdapterRunLauncher,
    StubMappingProposer,
)

_CSV = "field,description\norder_id,The id\ncustomer,End customer\n"
_SAMPLE = {"orders.csv": "ORDER_ID,CUSTOMER\n1,Acme\n"}


def _service() -> tuple[MappingService, InMemoryMappingJobRepository, StubMappingProposer]:
    jobs = InMemoryMappingJobRepository()
    proposer = StubMappingProposer()
    svc = MappingService(jobs, InMemoryCanonicalSchemaRepository(), StubAdapterRunLauncher())
    return svc, jobs, proposer


def test_register_schema_rejects_empty_csv() -> None:
    svc, _, _ = _service()
    with pytest.raises(EmptyCanonicalSchema):
        svc.register_schema("empty", "field,description\n")


def test_register_then_list_and_count() -> None:
    svc, _, _ = _service()
    svc.register_schema("orders", _CSV)
    assert svc.list_schemas() == ["orders"]
    assert svc.field_count("orders") == 2


def test_submit_requires_a_canonical_source() -> None:
    svc, _, _ = _service()
    with pytest.raises(NoCanonicalFields):
        svc.submit_job(erp_name="NetSuite", sample_files=_SAMPLE)


def test_submit_with_unknown_schema_raises() -> None:
    svc, _, _ = _service()
    with pytest.raises(CanonicalSchemaNotFound):
        svc.submit_job(erp_name="NetSuite", sample_files=_SAMPLE, schema_name="nope")


def test_submit_requires_at_least_one_sample() -> None:
    svc, _, _ = _service()
    with pytest.raises(ValueError, match="sample"):
        svc.submit_job(erp_name="NetSuite", sample_files={}, canonical_fields_csv=_CSV)


def test_full_flow_inline_csv_processes_and_approves() -> None:
    svc, jobs, proposer = _service()
    job = svc.submit_job(erp_name="NetSuite", sample_files=_SAMPLE, canonical_fields_csv=_CSV)
    assert job.status is MappingStatus.PENDING
    assert job.job_id.startswith("map_")

    # not ready to approve until the worker has run it
    with pytest.raises(MappingNotReady):
        svc.approve(job.job_id)

    claimed = process_pending_jobs(jobs, proposer)
    assert claimed == 1

    done = svc.get_job(job.job_id)
    assert done is not None and done.status is MappingStatus.DONE
    # the stub maps exact case-insensitive name matches: ORDER_ID->order_id, CUSTOMER->customer
    assert {e.canonical_field for e in (done.result or [])} == {"order_id", "customer"}

    approved = svc.approve(job.job_id)
    assert approved.adapter_run_id is not None
    run = svc.get_adapter_run(job.job_id)
    assert run is not None and run.status == "DONE" and run.branch


def test_submit_resolves_registered_schema_text() -> None:
    svc, jobs, proposer = _service()
    svc.register_schema("orders", _CSV)
    job = svc.submit_job(erp_name="SAP", sample_files=_SAMPLE, schema_name="orders")
    assert job.canonical_fields_csv == _CSV
    assert job.schema_name == "orders"


def test_claim_pending_marks_processing_and_respects_limit() -> None:
    jobs = InMemoryMappingJobRepository()
    svc = MappingService(jobs, InMemoryCanonicalSchemaRepository(), StubAdapterRunLauncher())
    ids = [
        svc.submit_job(erp_name=f"erp{i}", sample_files=_SAMPLE, canonical_fields_csv=_CSV).job_id
        for i in range(3)
    ]
    claimed = jobs.claim_pending(limit=2)
    assert len(claimed) == 2
    assert all(j.status is MappingStatus.PROCESSING for j in claimed)
    # the third is still pending and claimable afterwards
    remaining = jobs.claim_pending(limit=5)
    assert len(remaining) == 1
    assert remaining[0].job_id == ids[2]


def test_list_jobs_keeps_every_erp_newest_first() -> None:
    jobs = InMemoryMappingJobRepository()
    svc = MappingService(jobs, InMemoryCanonicalSchemaRepository(), StubAdapterRunLauncher())
    first = svc.submit_job(erp_name="NetSuite", sample_files=_SAMPLE, canonical_fields_csv=_CSV)
    second = svc.submit_job(
        erp_name="SAP",
        sample_files={"orders.csv": _SAMPLE["orders.csv"], "invoices.csv": "INVOICE_ID\n9\n"},
        canonical_fields_csv=_CSV,
    )
    first.created_at = datetime(2026, 1, 1, tzinfo=UTC)
    second.created_at = datetime(2026, 1, 2, tzinfo=UTC)
    jobs.update(first)
    jobs.update(second)
    listed = svc.list_jobs()
    assert [job.erp_name for job in listed] == ["SAP", "NetSuite"]
    assert set(listed[0].sample_exports) == {"orders.csv", "invoices.csv"}
