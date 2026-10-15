from __future__ import annotations

from datetime import UTC, datetime

import pytest

from src.modules.integration.mapping.application.processing import process_pending_jobs
from src.modules.integration.mapping.application.service import MappingService
from src.modules.integration.mapping.domain.errors import (
    CanonicalSchemaNotFound,
    ConnectionNotFound,
    EmptyCanonicalSchema,
    ErpTypeNotEligible,
    MappingNotReady,
    NoCanonicalFields,
    ProbeFailed,
)
from src.modules.integration.mapping.domain.models import MappingStatus
from src.modules.integration.mapping.infrastructure.memory import (
    InMemoryCanonicalSchemaRepository,
    InMemoryMappingJobRepository,
    StubAdapterRunLauncher,
    StubMappingProposer,
)
from src.modules.reference.connections.domain.models import ErpConnection
from src.modules.reference.connections.infrastructure.memory import InMemoryConnectionRepository
from src.shared.erp_probe import ProbeSample, SampleRequestSpec, StubErpProbe
from src.shared.secrets import EnvSecretStore
from src.shared.types import ConnectionId

_CSV = "field,description\norder_id,The id\ncustomer,End customer\n"
_SAMPLE = {"orders.csv": "ORDER_ID,CUSTOMER\n1,Acme\n"}


def _add_connection(
    connections: InMemoryConnectionRepository,
    *,
    erp_type: str = "NETSUITE",
    instance_label: str = "NetSuite",
    auth_type: str = "NONE",
    connection_id: str | None = None,
) -> str:
    slug = instance_label.lower().replace(" ", "_")
    connection_id = connection_id or f"conn_{erp_type.lower()}_{slug}"
    connections.add(
        ErpConnection(
            connection_id=ConnectionId(connection_id),
            erp_type=erp_type,
            instance_label=instance_label,
            base_url="http://erp.example.invalid",
            credentials={},
            secret_ref="env:UNUSED",
            auth_type=auth_type,
        )
    )
    return connection_id


def _make_service(
    jobs: InMemoryMappingJobRepository,
    connections: InMemoryConnectionRepository | None = None,
    *,
    probe=None,
    has_adapter=lambda _erp_type: False,
) -> MappingService:
    return MappingService(
        jobs,
        InMemoryCanonicalSchemaRepository(),
        StubAdapterRunLauncher(),
        probe or StubErpProbe(),
        EnvSecretStore(),
        connections or InMemoryConnectionRepository(),
        has_adapter,
    )


_ServiceFixture = tuple[
    MappingService, InMemoryMappingJobRepository, StubMappingProposer, InMemoryConnectionRepository
]


def _service() -> _ServiceFixture:
    jobs = InMemoryMappingJobRepository()
    connections = InMemoryConnectionRepository()
    proposer = StubMappingProposer()
    svc = _make_service(jobs, connections)
    return svc, jobs, proposer, connections


def test_register_schema_rejects_empty_csv() -> None:
    svc, _, _, _ = _service()
    with pytest.raises(EmptyCanonicalSchema):
        svc.register_schema("empty", "field,description\n")


def test_register_then_list_and_count() -> None:
    svc, _, _, _ = _service()
    svc.register_schema("orders", _CSV)
    assert svc.list_schemas() == ["orders"]
    assert svc.field_count("orders") == 2


def test_submit_rejects_an_unknown_connection() -> None:
    svc, _, _, _ = _service()
    with pytest.raises(ConnectionNotFound):
        svc.submit_job(connection_id="conn_nope", sample_files=_SAMPLE, canonical_fields_csv=_CSV)


def test_submit_rejects_a_connection_whose_erp_type_already_has_an_adapter() -> None:
    jobs = InMemoryMappingJobRepository()
    connections = InMemoryConnectionRepository()
    connection_id = _add_connection(connections, erp_type="ODOO")
    svc = _make_service(jobs, connections, has_adapter=lambda t: t == "ODOO")
    with pytest.raises(ErpTypeNotEligible, match="already has a working adapter"):
        svc.submit_job(connection_id=connection_id, sample_files=_SAMPLE, canonical_fields_csv=_CSV)


def test_submit_rejects_a_second_job_for_the_same_erp_type() -> None:
    """ADR-0022: a second connection of an erp_type already being mapped is blocked too —
    not just the first connection used."""
    jobs = InMemoryMappingJobRepository()
    connections = InMemoryConnectionRepository()
    first = _add_connection(connections, erp_type="SHOPIFY", instance_label="Shopify store 1")
    svc = _make_service(jobs, connections)
    svc.submit_job(connection_id=first, sample_files=_SAMPLE, canonical_fields_csv=_CSV)

    second = _add_connection(connections, erp_type="SHOPIFY", instance_label="Shopify store 2")
    with pytest.raises(ErpTypeNotEligible, match="already has mapping job"):
        svc.submit_job(connection_id=second, sample_files=_SAMPLE, canonical_fields_csv=_CSV)


def test_submit_requires_a_canonical_source() -> None:
    svc, _, _, connections = _service()
    connection_id = _add_connection(connections)
    with pytest.raises(NoCanonicalFields):
        svc.submit_job(connection_id=connection_id, sample_files=_SAMPLE)


def test_submit_with_unknown_schema_raises() -> None:
    svc, _, _, connections = _service()
    connection_id = _add_connection(connections)
    with pytest.raises(CanonicalSchemaNotFound):
        svc.submit_job(connection_id=connection_id, sample_files=_SAMPLE, schema_name="nope")


def test_submit_requires_at_least_one_sample() -> None:
    svc, _, _, connections = _service()
    connection_id = _add_connection(connections)
    with pytest.raises(ValueError, match="sample"):
        svc.submit_job(connection_id=connection_id, sample_files={}, canonical_fields_csv=_CSV)


def test_full_flow_inline_csv_processes_and_approves() -> None:
    svc, jobs, proposer, connections = _service()
    connection_id = _add_connection(connections, instance_label="NetSuite")
    job = svc.submit_job(
        connection_id=connection_id, sample_files=_SAMPLE, canonical_fields_csv=_CSV
    )
    assert job.status is MappingStatus.PENDING
    assert job.job_id.startswith("map_")
    assert job.erp_name == "NetSuite"
    assert job.connection_id == connection_id

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
    svc, jobs, proposer, connections = _service()
    svc.register_schema("orders", _CSV)
    connection_id = _add_connection(connections, erp_type="SAP")
    job = svc.submit_job(connection_id=connection_id, sample_files=_SAMPLE, schema_name="orders")
    assert job.canonical_fields_csv == _CSV
    assert job.schema_name == "orders"


def test_claim_pending_marks_processing_and_respects_limit() -> None:
    jobs = InMemoryMappingJobRepository()
    connections = InMemoryConnectionRepository()
    svc = _make_service(jobs, connections)
    ids = [
        svc.submit_job(
            connection_id=_add_connection(
                connections, erp_type=f"ERP{i}", instance_label=f"erp{i}"
            ),
            sample_files=_SAMPLE,
            canonical_fields_csv=_CSV,
        ).job_id
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
    connections = InMemoryConnectionRepository()
    svc = _make_service(jobs, connections)
    netsuite = _add_connection(connections, erp_type="NETSUITE", instance_label="NetSuite")
    sap = _add_connection(connections, erp_type="SAP", instance_label="SAP")
    first = svc.submit_job(connection_id=netsuite, sample_files=_SAMPLE, canonical_fields_csv=_CSV)
    second = svc.submit_job(
        connection_id=sap,
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


def test_eligible_connections_excludes_adapted_and_in_flight_types() -> None:
    jobs = InMemoryMappingJobRepository()
    connections = InMemoryConnectionRepository()
    adapted = _add_connection(connections, erp_type="ODOO", instance_label="Odoo")
    in_flight = _add_connection(connections, erp_type="SHOPIFY", instance_label="Shopify")
    open_one = _add_connection(connections, erp_type="BIGCOMMERCE", instance_label="BigCommerce")
    svc = _make_service(jobs, connections, has_adapter=lambda t: t == "ODOO")
    svc.submit_job(connection_id=in_flight, sample_files=_SAMPLE, canonical_fields_csv=_CSV)

    eligible_ids = {c.connection_id for c in svc.eligible_connections()}
    assert eligible_ids == {open_one}
    assert adapted not in eligible_ids
    assert in_flight not in eligible_ids


class _FailingProbe:
    def fetch_samples(self, *, base_url, auth, secret_ref, requests):
        return [ProbeSample(label=r.label, error="cannot reach ERP: timed out") for r in requests]


def test_probe_samples_writes_secret_and_returns_results() -> None:
    jobs = InMemoryMappingJobRepository()
    connections = InMemoryConnectionRepository()
    connection_id = _add_connection(connections, auth_type="API_KEY_HEADER")
    svc = _make_service(jobs, connections)
    results = svc.probe_samples(
        connection_id=connection_id,
        requests=[SampleRequestSpec(label="orders", path="/orders")],
    )
    assert len(results) == 1 and results[0].error is None


def test_submit_job_from_probe_builds_a_job_from_fetched_samples() -> None:
    jobs = InMemoryMappingJobRepository()
    connections = InMemoryConnectionRepository()
    connection_id = _add_connection(connections, instance_label="Acme ERP")
    svc = _make_service(jobs, connections)
    job = svc.submit_job_from_probe(
        connection_id=connection_id,
        requests=[SampleRequestSpec(label="orders", path="/orders")],
        canonical_fields_csv=_CSV,
    )
    assert job.erp_name == "Acme ERP"
    assert "orders.json" in job.sample_exports


def test_approve_rejects_a_second_job_for_an_erp_type_already_approved() -> None:
    """The gap found during manual testing: two connections of the same erp_type can
    both reach a DONE, unapproved mapping job before either is reviewed (the submit-time
    guard doesn't block a DONE-unapproved sibling, by design). Approving the first must
    not silently let the second one through too — that's the actual regression this
    whole feature exists to prevent."""
    jobs = InMemoryMappingJobRepository()
    connections = InMemoryConnectionRepository()
    first_conn = _add_connection(connections, erp_type="SHOPIFY", instance_label="Store A")
    svc = _make_service(jobs, connections)
    first = svc.submit_job(
        connection_id=first_conn, sample_files=_SAMPLE, canonical_fields_csv=_CSV
    )

    # Finish the first job's proposal (DONE, unapproved) before the second is even
    # submitted — simulating the real worker, so the submit-time guard sees nothing
    # blocking yet and lets the second job in too.
    first.status = MappingStatus.DONE
    first.result = []
    jobs.update(first)

    second_conn = _add_connection(connections, erp_type="SHOPIFY", instance_label="Store B")
    second = svc.submit_job(
        connection_id=second_conn, sample_files=_SAMPLE, canonical_fields_csv=_CSV
    )
    second.status = MappingStatus.DONE
    second.result = []
    jobs.update(second)

    svc.approve(first.job_id)  # the first approval succeeds, generating the one adapter
    with pytest.raises(ErpTypeNotEligible, match="already approved"):
        svc.approve(second.job_id)


def test_submit_job_from_probe_raises_on_any_failed_request() -> None:
    jobs = InMemoryMappingJobRepository()
    connections = InMemoryConnectionRepository()
    connection_id = _add_connection(connections, instance_label="Acme ERP")
    svc = _make_service(jobs, connections, probe=_FailingProbe())
    with pytest.raises(ProbeFailed, match="timed out"):
        svc.submit_job_from_probe(
            connection_id=connection_id,
            requests=[SampleRequestSpec(label="orders", path="/orders")],
            canonical_fields_csv=_CSV,
        )
    # the failed probe must never have created a job
    assert jobs.list_recent() == []


def test_connection_mapping_status_distinguishes_awaiting_adapter_from_needs_mapping() -> None:
    """The gap a user caught live: `hasAdapter=false` alone doesn't mean "go map it" —
    a connection whose type already has an approved-but-not-yet-merged job has nothing
    left to do on the Mapping page, and the UI needs to say that, not "Needs mapping"."""
    jobs = InMemoryMappingJobRepository()
    connections = InMemoryConnectionRepository()

    adapted_id = _add_connection(connections, erp_type="ODOO", instance_label="Odoo")
    in_flight_conn_id = _add_connection(connections, erp_type="SHOPIFY", instance_label="Shopify")
    approved_conn_id = _add_connection(
        connections, erp_type="BIGCOMMERCE", instance_label="BigCommerce"
    )
    open_conn_id = _add_connection(connections, erp_type="SQUARE", instance_label="Square")
    adapted = connections.get(ConnectionId(adapted_id))
    open_conn = connections.get(ConnectionId(open_conn_id))

    svc = _make_service(jobs, connections, has_adapter=lambda t: t == "ODOO")
    in_flight = svc.submit_job(
        connection_id=in_flight_conn_id, sample_files=_SAMPLE, canonical_fields_csv=_CSV
    )
    approved = svc.submit_job(
        connection_id=approved_conn_id, sample_files=_SAMPLE, canonical_fields_csv=_CSV
    )
    approved.status = MappingStatus.DONE
    approved.result = []
    jobs.update(approved)
    svc.approve(approved.job_id)

    assert adapted is not None
    assert svc.connection_mapping_status(adapted) == "ADAPTER_READY"
    in_flight_conn = connections.get(ConnectionId(in_flight_conn_id))
    assert in_flight_conn is not None
    assert svc.connection_mapping_status(in_flight_conn) == "MAPPING_IN_PROGRESS"
    assert in_flight.status is MappingStatus.PENDING  # sanity: still the in-flight job
    approved_conn = connections.get(ConnectionId(approved_conn_id))
    assert approved_conn is not None
    assert svc.connection_mapping_status(approved_conn) == "AWAITING_ADAPTER"
    assert open_conn is not None
    assert svc.connection_mapping_status(open_conn) == "NEEDS_MAPPING"
