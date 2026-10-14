"""Settings — all configuration in one typed place, sourced from env (12-factor).

Plain stdlib dataclass (no third-party dependency) reading environment variables.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache

_ALL_WORKER_ROLES = frozenset(
    {
        "order-processing",
        "order-delivery",
        "order-fulfillment",
        "projections",
        "webhook-dispatch",
        "relay",
        "reconcile",
        "mapping",
    }
)


@dataclass(frozen=True)
class Settings:
    profile: str  # "memory" (local dev/tests, no infra) | "postgres" (Postgres + SNS/SQS)
    database_url: str
    aws_endpoint_url: str | None
    aws_region: str
    domain_topic_arn: str
    # "real" (dispatch via the adapter registry) | "stub" (force StubErpAdapter for every ERP type)
    erp_adapter_mode: str
    # OdooAdapter-specific; a new ERP adapter gets its own timeout setting if it needs one
    erp_odoo_timeout_seconds: float
    log_level: str
    reconcile_interval_seconds: int
    worker_roles: frozenset[str]  # which of {order-processing, order-delivery,
    # order-fulfillment, projections, webhook-dispatch, relay, reconcile} this `worker`
    # process runs — "all" (default) runs
    # every one, matching today's single-process behavior (ADR-0010's role split, Part 1)
    cognito_user_pool_id: str | None
    cognito_client_id: str | None
    # OAuth scope namespace for client_credentials (M2M) tokens:
    # {this}/tenant.<id>, {this}/role.<ROLE>
    cognito_resource_server_id: str
    cors_allowed_origins: list[str]  # the UI's origin(s) — e.g. an S3/CloudFront URL in prod
    # ERP field-mapping proposer (operator AdminOps "ERP mapping" tab):
    # the Bedrock model the `mapping` worker calls, and the base URL of the separate
    # erp-agent-service the "approve & implement" action hands an approved mapping to.
    mapping_bedrock_model_id: str
    agent_service_url: str
    # JsonPlaceholderDemoAdapter-specific (its own timeout, not reused from Odoo's) —
    # defaulted so existing `Settings(...)` call sites don't all need updating for a
    # second ERP's adapter-local knob.
    erp_jsonplaceholder_demo_timeout_seconds: float = 10.0


def _parse_worker_roles(raw: str) -> frozenset[str]:
    if raw.strip().lower() == "all":
        return _ALL_WORKER_ROLES
    roles = frozenset(r.strip() for r in raw.split(",") if r.strip())
    unknown = roles - _ALL_WORKER_ROLES
    if unknown:
        raise ValueError(
            f"unknown WORKER_ROLE value(s): {sorted(unknown)} — valid: {sorted(_ALL_WORKER_ROLES)}"
        )
    return roles


@lru_cache
def get_settings() -> Settings:
    return Settings(
        profile=os.environ.get("APP_PROFILE", "memory"),
        database_url=os.environ.get(
            "DATABASE_URL", "postgresql+psycopg2://portal:portal@localhost:5432/portal"
        ),
        aws_endpoint_url=os.environ.get("AWS_ENDPOINT_URL"),  # http://localhost:4566 for floci
        aws_region=os.environ.get("AWS_REGION", "us-east-1"),
        domain_topic_arn=os.environ.get(
            "DOMAIN_TOPIC_ARN", "arn:aws:sns:us-east-1:000000000000:platform-domain-events.fifo"
        ),
        erp_adapter_mode=os.environ.get("ERP_ADAPTER_MODE", "real"),
        erp_odoo_timeout_seconds=float(os.environ.get("ERP_ODOO_TIMEOUT_SECONDS", "10")),
        log_level=os.environ.get("LOG_LEVEL", "INFO"),
        reconcile_interval_seconds=int(os.environ.get("RECONCILE_INTERVAL_SECONDS", "900")),
        worker_roles=_parse_worker_roles(os.environ.get("WORKER_ROLE", "all")),
        cognito_user_pool_id=os.environ.get("COGNITO_USER_POOL_ID"),
        cognito_client_id=os.environ.get("COGNITO_CLIENT_ID"),
        cognito_resource_server_id=os.environ.get("COGNITO_RESOURCE_SERVER_ID", "o2c"),
        cors_allowed_origins=[
            origin.strip()
            for origin in os.environ.get(
                "CORS_ALLOWED_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173"
            ).split(",")
            if origin.strip()
        ],
        mapping_bedrock_model_id=os.environ.get(
            "MAPPING_BEDROCK_MODEL_ID", "us.anthropic.claude-haiku-4-5-20251001-v1:0"
        ),
        agent_service_url=os.environ.get("AGENT_SERVICE_URL", "http://localhost:8002"),
        erp_jsonplaceholder_demo_timeout_seconds=float(
            os.environ.get("ERP_JSONPLACEHOLDER_DEMO_TIMEOUT_SECONDS", "10")
        ),
    )
