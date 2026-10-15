"""Worker entrypoint (postgres/AWS deployment).

Builds the postgres-profile container (same composition root as the API), then starts:
- one `SqsConsumerRunner` per queue (order-processing / order-delivery / projections /
  webhook-dispatch), each handler wrapped so it dedupes on `event_id` via
  `processed_events` BEFORE calling into the module handler — the handler itself only has
  to be correct, not idempotent (item A's carried-forward note: the projection store's
  own conflict-handling is a second line of defense, not a substitute for this).
- the outbox `RelayRunner` (Postgres outbox -> SNS FIFO topic).
- the `ReconcileScheduler` (periodic fallback sweep for missed webhooks).

`webhook-dispatch.fifo` now has a consumer (`container.webhook_dispatcher.handle`) —
outbound webhooks are still secondary to GraphQL as the primary read path, but the queue
is no longer just provisioned-and-idle: a reseller-registered endpoint actually gets
called. `WebhookDispatchService` raises for redrive itself (mirroring `DeliveryHandler`),
so this consumer needs no special handling beyond the same dedupe wrapper as the others.

Not built: per-connection circuit breaker (plan item C mentions it; deferred — a
transient ERP failure today just raises `DeliveryRetry`, which the SQS redrive/backoff
already turns into bounded retries. A breaker that trips PER CONNECTION and short-circuits
without hitting the ERP is real, separable follow-up work, not needed to get the async
pipeline running end-to-end).
"""

from __future__ import annotations

import logging
import signal
import threading
from typing import TYPE_CHECKING

import boto3
from sqlalchemy import Column, MetaData, String, Table, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert

from src.composition import build_container
from src.modules.integration.mapping.application.processing import process_pending_jobs
from src.shared.config import get_settings
from src.shared.messaging.aws import SnsFifoPublisher, SqsConsumerRunner
from src.shared.messaging.azure import ServiceBusConsumerRunner, ServiceBusPublisher
from src.shared.persistence.engine import get_session_factory
from src.shared.persistence.relay import OutboxRelay

from .connection_lock import PostgresConnectionLock
from .relay_runner import RelayRunner
from .scheduler import ReconcileScheduler

if TYPE_CHECKING:
    from types import FrameType

    from sqlalchemy.orm import Session, sessionmaker

    from src.shared.eventsourcing import StoredEvent
    from src.shared.types import ConnectionId

log = logging.getLogger("worker")

_TERMINAL_STATES = ("CLOSED", "CANCELLED", "REJECTED")
_MAPPING_POLL_SECONDS = 5.0

_processed_events = Table(
    "processed_events",
    MetaData(),
    Column("consumer", String, primary_key=True),
    Column("event_id", String, primary_key=True),
)


def _dedupe(consumer: str, session_factory: sessionmaker[Session], handler):
    """Wrap a handler so at-least-once redelivery of the same `event_id` to THIS consumer
    is a no-op. Marks processed only after `handler` returns without raising, so a failed
    attempt is still retried (and eventually redriven to the DLQ) rather than silently
    swallowed."""

    def wrapped(event: StoredEvent) -> None:
        session = session_factory()
        try:
            already_seen = (
                session.execute(
                    select(_processed_events.c.event_id).where(
                        _processed_events.c.consumer == consumer,
                        _processed_events.c.event_id == event.event_id,
                    )
                ).first()
                is not None
            )
        finally:
            session.close()
        if already_seen:
            log.info("skip duplicate event_id=%s consumer=%s", event.event_id, consumer)
            return

        handler(event)

        session = session_factory()
        try:
            stmt = pg_insert(_processed_events).values(consumer=consumer, event_id=event.event_id)
            stmt = stmt.on_conflict_do_nothing(index_elements=["consumer", "event_id"])
            session.execute(stmt)
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    return wrapped


def _queue_url(sqs: object, name: str) -> str:
    return sqs.get_queue_url(QueueName=name)["QueueUrl"]  # type: ignore[attr-defined]


def _open_orders_provider(session_factory: sessionmaker[Session]):
    placeholders = ", ".join(f"'{s}'" for s in _TERMINAL_STATES)

    def provider(connection_id: ConnectionId) -> list[str]:
        session = session_factory()
        try:
            rows = session.execute(
                text(
                    f"SELECT erp_order_id FROM orders "
                    f"WHERE owning_connection_id = :cid AND erp_order_id IS NOT NULL "
                    f"AND state NOT IN ({placeholders})"
                ),
                {"cid": str(connection_id)},
            ).all()
        finally:
            session.close()
        return [row[0] for row in rows]

    return provider


def _run_mapping_poll(container, stop: threading.Event) -> None:  # type: ignore[no-untyped-def]
    """Poll the `mapping_jobs` table for PENDING proposal jobs and run them through the
    LLM (`container.mapping_proposer`). A polling loop, not an SQS consumer: these are
    manual, low-volume, per-new-ERP runs, and the former standalone service worked the
    same way. Sleeps only when it finds nothing, so a backlog drains promptly."""
    while not stop.is_set():
        try:
            processed = process_pending_jobs(container.mapping_jobs, container.mapping_proposer)
        except Exception:
            log.exception("mapping poll iteration failed")
            processed = 0
        if processed == 0:
            stop.wait(_MAPPING_POLL_SECONDS)


def main() -> None:  # pragma: no cover - process entrypoint
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

    settings = get_settings()
    if settings.profile != "postgres":
        raise SystemExit(f"worker requires APP_PROFILE=postgres (got {settings.profile!r})")

    roles = settings.worker_roles
    if not roles:
        raise SystemExit("WORKER_ROLE resolved to no roles — nothing for this process to do")

    container = build_container(settings)
    session_factory = get_session_factory(settings.database_url)
    assert container.reconcile_sweeper is not None  # guaranteed by the postgres profile

    threads: list[threading.Thread] = []

    # (role, handler) — only the ones this process's roles include are built at all: no
    # queue/subscription lookup, no thread, for a role this process doesn't run.
    consumer_specs = [
        ("order-processing", container.order_processor.handle),
        ("order-delivery", container.delivery_handler.handle),
        ("order-fulfillment", container.order_fulfillment_consumer.handle),
        ("projections", container.order_projector.handle),
        ("webhook-dispatch", container.webhook_dispatcher.handle),
    ]

    if settings.cloud_provider == "azure":
        # ADR-0023: Service Bus subscription names match the role name exactly, no
        # ".fifo" suffix convention (infra/azure/modules/messaging) — unlike SQS below.
        assert (
            settings.azure_servicebus_namespace
        ), "AZURE_SERVICEBUS_NAMESPACE required when CLOUD_PROVIDER=azure"
        if "relay" in roles:
            publisher = ServiceBusPublisher(
                settings.azure_servicebus_namespace,
                settings.azure_servicebus_topic,
                managed_identity_client_id=settings.azure_managed_identity_client_id,
            )
            relay = RelayRunner(OutboxRelay(session_factory, publisher))
            threads.append(
                threading.Thread(target=relay.run_forever, name="outbox-relay", daemon=True)
            )

        for role, handler in consumer_specs:
            if role not in roles:
                continue
            consumer = ServiceBusConsumerRunner(
                settings.azure_servicebus_namespace,
                settings.azure_servicebus_topic,
                role,
                _dedupe(role, session_factory, handler),
                managed_identity_client_id=settings.azure_managed_identity_client_id,
            )
            threads.append(
                threading.Thread(target=consumer.run_forever, name=f"consumer-{role}", daemon=True)
            )
    else:
        sqs = boto3.client(
            "sqs", endpoint_url=settings.aws_endpoint_url, region_name=settings.aws_region
        )

        if "relay" in roles:
            publisher = SnsFifoPublisher(
                settings.domain_topic_arn,
                endpoint_url=settings.aws_endpoint_url,
                region_name=settings.aws_region,
            )
            relay = RelayRunner(OutboxRelay(session_factory, publisher))
            threads.append(
                threading.Thread(target=relay.run_forever, name="outbox-relay", daemon=True)
            )

        for role, handler in consumer_specs:
            if role not in roles:
                continue
            consumer = SqsConsumerRunner(
                _queue_url(sqs, f"{role}.fifo"),
                _dedupe(role, session_factory, handler),
                endpoint_url=settings.aws_endpoint_url,
                region_name=settings.aws_region,
            )
            threads.append(
                threading.Thread(target=consumer.run_forever, name=f"consumer-{role}", daemon=True)
            )

    if "reconcile" in roles:
        scheduler = ReconcileScheduler(
            container.reconcile_sweeper,
            connections_provider=lambda: [
                c.connection_id for c in container.connections.list_active()
            ],
            open_orders_provider=_open_orders_provider(session_factory),
            interval_seconds=settings.reconcile_interval_seconds,
            lock=PostgresConnectionLock(session_factory),
        )
        threads.append(
            threading.Thread(target=scheduler.run_forever, name="reconcile-scheduler", daemon=True)
        )

    stop = threading.Event()

    def _shutdown(signum: int, _frame: FrameType | None) -> None:
        log.info("received signal %s, shutting down", signum)
        stop.set()

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    if "mapping" in roles:
        threads.append(
            threading.Thread(
                target=_run_mapping_poll, args=(container, stop), name="mapping-poll", daemon=True
            )
        )

    log.info("worker starting: roles=%s, %d thread(s)", sorted(roles), len(threads))
    for thread in threads:
        thread.start()

    # Threads are daemons (run_forever loops never return); block here so the process
    # stays up, and exit promptly once a shutdown signal flips `stop`.
    stop.wait()
    log.info("worker stopped")


if __name__ == "__main__":
    main()
