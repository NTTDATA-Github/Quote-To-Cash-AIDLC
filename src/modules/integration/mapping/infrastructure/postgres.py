"""Postgres-backed mapping repositories — the two ports on `canonical_schemas` and
`mapping_jobs` (migration 0015). SQLAlchemy Core, same conventions as the connections
repo: own `MetaData`, injected `sessionmaker`, a session per method, upsert via
`on_conflict_do_update`.

`claim_pending` uses `FOR UPDATE SKIP LOCKED` so more than one `mapping` worker replica can
run without handing the same job to two of them (the former standalone service punted on
this with a single-replica note; the portal does it properly).
"""

from __future__ import annotations

from dataclasses import asdict
from typing import TYPE_CHECKING

from sqlalchemy import Column, DateTime, MetaData, String, Table, Text, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import insert as pg_insert

from ..domain.models import CanonicalSchema, MappingEntry, MappingJob, MappingStatus

if TYPE_CHECKING:
    from sqlalchemy.engine import Row
    from sqlalchemy.orm import Session, sessionmaker

_metadata = MetaData()

canonical_schemas_table = Table(
    "canonical_schemas",
    _metadata,
    Column("name", String, primary_key=True),
    Column("csv_text", Text, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
)

mapping_jobs_table = Table(
    "mapping_jobs",
    _metadata,
    Column("job_id", String, primary_key=True),
    Column("erp_name", String, nullable=False),
    Column("status", String, nullable=False),
    Column("canonical_fields_csv", Text, nullable=False),
    Column("sample_exports", JSONB, nullable=False, server_default="{}"),
    Column("schema_name", String),
    Column("result", JSONB),
    Column("error", Text),
    Column("adapter_run_id", String),
    Column("created_at", DateTime(timezone=True), nullable=False),
)


def _schema_to_model(row: Row) -> CanonicalSchema:
    return CanonicalSchema(name=row.name, csv_text=row.csv_text, created_at=row.created_at)


def _result_to_entries(raw: list | None) -> list[MappingEntry] | None:
    if raw is None:
        return None
    return [
        MappingEntry(
            erp_field=item["erp_field"],
            canonical_field=item["canonical_field"],
            sample_data=item["sample_data"],
            confidence=int(item["confidence"]),
        )
        for item in raw
    ]


def _job_to_model(row: Row) -> MappingJob:
    return MappingJob(
        job_id=row.job_id,
        erp_name=row.erp_name,
        status=MappingStatus(row.status),
        canonical_fields_csv=row.canonical_fields_csv,
        sample_exports=dict(row.sample_exports or {}),
        schema_name=row.schema_name,
        result=_result_to_entries(row.result),
        error=row.error,
        adapter_run_id=row.adapter_run_id,
        created_at=row.created_at,
    )


def _job_values(job: MappingJob) -> dict:
    return {
        "job_id": job.job_id,
        "erp_name": job.erp_name,
        "status": job.status.value,
        "canonical_fields_csv": job.canonical_fields_csv,
        "sample_exports": dict(job.sample_exports),
        "schema_name": job.schema_name,
        "result": None if job.result is None else [asdict(e) for e in job.result],
        "error": job.error,
        "adapter_run_id": job.adapter_run_id,
        "created_at": job.created_at,
    }


class PostgresCanonicalSchemaRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def add(self, schema: CanonicalSchema) -> None:
        values = {
            "name": schema.name,
            "csv_text": schema.csv_text,
            "created_at": schema.created_at,
        }
        session = self._session_factory()
        try:
            stmt = pg_insert(canonical_schemas_table).values(**values)
            stmt = stmt.on_conflict_do_update(
                index_elements=["name"],
                set_={"csv_text": schema.csv_text},
            )
            session.execute(stmt)
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def get(self, name: str) -> CanonicalSchema | None:
        session = self._session_factory()
        try:
            row = session.execute(
                select(canonical_schemas_table).where(canonical_schemas_table.c.name == name)
            ).first()
        finally:
            session.close()
        return _schema_to_model(row) if row is not None else None

    def list_names(self) -> list[str]:
        session = self._session_factory()
        try:
            rows = session.execute(
                select(canonical_schemas_table.c.name).order_by(canonical_schemas_table.c.name)
            ).all()
        finally:
            session.close()
        return [row[0] for row in rows]


class PostgresMappingJobRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def add(self, job: MappingJob) -> None:
        session = self._session_factory()
        try:
            session.execute(mapping_jobs_table.insert().values(**_job_values(job)))
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def get(self, job_id: str) -> MappingJob | None:
        session = self._session_factory()
        try:
            row = session.execute(
                select(mapping_jobs_table).where(mapping_jobs_table.c.job_id == job_id)
            ).first()
        finally:
            session.close()
        return _job_to_model(row) if row is not None else None

    def list_recent(self, limit: int = 50) -> list[MappingJob]:
        session = self._session_factory()
        try:
            rows = session.execute(
                select(mapping_jobs_table)
                .order_by(mapping_jobs_table.c.created_at.desc())
                .limit(limit)
            ).all()
        finally:
            session.close()
        return [_job_to_model(row) for row in rows]

    def update(self, job: MappingJob) -> None:
        session = self._session_factory()
        try:
            session.execute(
                mapping_jobs_table.update()
                .where(mapping_jobs_table.c.job_id == job.job_id)
                .values(
                    status=job.status.value,
                    result=None if job.result is None else [asdict(e) for e in job.result],
                    error=job.error,
                    adapter_run_id=job.adapter_run_id,
                )
            )
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def claim_pending(self, limit: int = 5) -> list[MappingJob]:
        session = self._session_factory()
        try:
            rows = session.execute(
                select(mapping_jobs_table)
                .where(mapping_jobs_table.c.status == MappingStatus.PENDING.value)
                .order_by(mapping_jobs_table.c.created_at)
                .limit(limit)
                .with_for_update(skip_locked=True)
            ).all()
            jobs = [_job_to_model(row) for row in rows]
            if jobs:
                session.execute(
                    mapping_jobs_table.update()
                    .where(mapping_jobs_table.c.job_id.in_([j.job_id for j in jobs]))
                    .values(status=MappingStatus.PROCESSING.value)
                )
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()
        for job in jobs:
            job.status = MappingStatus.PROCESSING
        return jobs
