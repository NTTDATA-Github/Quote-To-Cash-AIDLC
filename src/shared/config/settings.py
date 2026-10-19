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
    profile: str  # "memory" (local dev/tests, no infra) | "postgres" (Postgres + Service Bus)
    database_url: str
    # Which cloud the "postgres" profile's secrets/messaging/identity/LLM adapters come
    # from (ADR-0023). Ignored by the "memory" profile, which uses none of them.
    aws_region: str
    azure_key_vault_uri: str | None
    azure_servicebus_namespace: str | None  # fully-qualified, e.g. "<ns>.servicebus.windows.net"
    azure_servicebus_topic: str
    # SAS connection string — takes priority over managed identity when set (see
    # messaging/azure.py). ADR-0023: avoids needing roleAssignments/write for the
    # "Azure Service Bus Data Sender/Receiver" RBAC roles.
    azure_servicebus_connection_string: str | None
    # The client id of THIS process's own user-assigned managed identity (api/worker each
    # have their own — infra/azure/modules/iam). None = fall back to DefaultAzureCredential
    # (local `az login`, or the only identity on the host).
    azure_managed_identity_client_id: str | None
    entra_tenant_id: str | None
    entra_client_id: str | None
    # Name of the Entra claim carrying the per-user tenant id — portal/user-flow
    # configured, not yet something Terraform can pin (see ADR-0023).
    entra_tenant_claim_name: str
    # Self-hosted Keycloak (ADR-0023 follow-up) — the real Azure IdentityProvider today,
    # since a real Entra External ID tenant doesn't exist yet. Full issuer URL, e.g.
    # "https://<keycloak-fqdn>/realms/o2c" (infra/azure's `keycloak_realm_url` output).
    keycloak_issuer: str | None
    keycloak_client_id: str
    # "real" (dispatch via the adapter registry) | "stub" (force StubErpAdapter for every ERP type)
    erp_adapter_mode: str
    # OdooAdapter-specific; a new ERP adapter gets its own timeout setting if it needs one
    erp_odoo_timeout_seconds: float
    # NetSuiteAdapter-specific — its own timeout, deliberately not shared with Odoo's
    erp_netsuite_timeout_seconds: float
    log_level: str
    reconcile_interval_seconds: int
    worker_roles: frozenset[str]  # which of {order-processing, order-delivery,
    # order-fulfillment, projections, webhook-dispatch, relay, reconcile} this `worker`
    # process runs — "all" (default) runs
    # every one, matching today's single-process behavior (ADR-0010's role split, Part 1)
    # OAuth scope namespace for client_credentials (M2M) tokens:
    # {this}/tenant.<id>, {this}/role.<ROLE>
    cors_allowed_origins: list[str]  # the UI's origin(s), e.g. the Front Door URL in prod
    # ERP field-mapping proposer (operator AdminOps "ERP mapping" tab):
    # the Bedrock model the `mapping` worker calls, and the base URL of the separate
    # erp-agent-service the "approve & implement" action hands an approved mapping to.
    mapping_bedrock_model_id: str
    # Anthropic model id for the direct Anthropic provider (ADR-0023) — not a Bedrock
    # inference-profile id.
    mapping_anthropic_model: str
    # Which LLM backend the mapping proposer uses: "bedrock" (AWS), "anthropic" (Anthropic
    # API), or "foundry" (Azure Foundry). Defaults to "anthropic" on azure, "bedrock" on aws.
    llm_provider: str | None
    # Azure Foundry endpoint URL (e.g., https://<region>.api.foundry.azure.com/...)
    # Required when llm_provider="foundry".
    foundry_endpoint: str | None
    # Azure Foundry API key. Optional — falls back to Key Vault's foundry-api-key secret.
    foundry_api_key: str | None
    # Override the mapping service's LLM provider independently: "bedrock", "anthropic",
    # "foundry" (Claude), or "openai" (GPT models). When not set, uses llm_provider above.
    mapping_llm_provider: str | None
    # OpenAI model for mapping (e.g., "gpt-4o"). Used when mapping_llm_provider="openai".
    mapping_openai_model: str
    agent_service_url: str
    # Local-dev-only escape hatch for GenericErpProbe's SSRF guard (ADR-0021) — the ERP
    # being tested (local Odoo, the NetSuite mock) is deliberately on localhost, which the
    # guard correctly refuses in a real deployment. Never set this in staging/production.
    erp_probe_allow_private_addresses: bool


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
        aws_region=os.environ.get("AWS_REGION", "us-east-1"),
        azure_key_vault_uri=os.environ.get("AZURE_KEY_VAULT_URI"),
        azure_servicebus_namespace=os.environ.get("AZURE_SERVICEBUS_NAMESPACE"),
        azure_servicebus_topic=os.environ.get("AZURE_SERVICEBUS_TOPIC", "platform-domain-events"),
        azure_servicebus_connection_string=os.environ.get("AZURE_SERVICEBUS_CONNECTION_STRING"),
        azure_managed_identity_client_id=os.environ.get("AZURE_MANAGED_IDENTITY_CLIENT_ID"),
        entra_tenant_id=os.environ.get("ENTRA_TENANT_ID"),
        entra_client_id=os.environ.get("ENTRA_CLIENT_ID"),
        entra_tenant_claim_name=os.environ.get("ENTRA_TENANT_CLAIM_NAME", "extension_tenant_id"),
        keycloak_issuer=os.environ.get("KEYCLOAK_ISSUER"),
        keycloak_client_id=os.environ.get("KEYCLOAK_CLIENT_ID", "o2c-portal"),
        erp_adapter_mode=os.environ.get("ERP_ADAPTER_MODE", "real"),
        erp_odoo_timeout_seconds=float(os.environ.get("ERP_ODOO_TIMEOUT_SECONDS", "10")),
        erp_netsuite_timeout_seconds=float(os.environ.get("ERP_NETSUITE_TIMEOUT_SECONDS", "10")),
        log_level=os.environ.get("LOG_LEVEL", "INFO"),
        reconcile_interval_seconds=int(os.environ.get("RECONCILE_INTERVAL_SECONDS", "900")),
        worker_roles=_parse_worker_roles(os.environ.get("WORKER_ROLE", "all")),
        cors_allowed_origins=[
            origin.strip()
            for origin in os.environ.get(
                "CORS_ALLOWED_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173"
            ).split(",")
            if origin.strip()
        ],
        mapping_bedrock_model_id=os.environ.get(
            "MAPPING_BEDROCK_MODEL_ID", "us.anthropic.claude-haiku-5-5-v1:0"
        ),
        mapping_anthropic_model=os.environ.get("MAPPING_ANTHROPIC_MODEL", "claude-haiku-5-5"),
        llm_provider=os.environ.get("LLM_PROVIDER"),
        foundry_endpoint=os.environ.get("FOUNDRY_ENDPOINT"),
        foundry_api_key=os.environ.get("FOUNDRY_API_KEY"),
        mapping_llm_provider=os.environ.get("MAPPING_LLM_PROVIDER"),
        mapping_openai_model=os.environ.get("MAPPING_OPENAI_MODEL", "gpt-4o"),
        agent_service_url=os.environ.get("AGENT_SERVICE_URL", "http://localhost:8002"),
        erp_probe_allow_private_addresses=os.environ.get(
            "ERP_PROBE_ALLOW_PRIVATE_ADDRESSES", "false"
        ).lower()
        == "true",
    )
