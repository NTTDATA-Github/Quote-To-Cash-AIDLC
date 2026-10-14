"""Connection domain model."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.shared.types import ConnectionId


class ErpType(str, Enum):
    """Every ERP type the platform knows about. Adding one here is step 4 of "add a new
    ERP" — see `integration/infrastructure/registry.py`'s module docstring for the full
    checklist (adapter class, status mapper, registry entry, then this enum member)."""

    ODOO = "ODOO"
    JSONPLACEHOLDER_DEMO = "JSONPLACEHOLDER_DEMO"


class ConnectionStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"


@dataclass
class ErpConnection:
    """One ERP instance (e.g. one Odoo database) — see `ErpType` for which ERPs are
    currently registered. Operator-only identity.

    `secret_ref` is a Secrets Manager reference — never the raw credential (SECURITY-12).
    `instance_label` is operator-only and must never reach a reseller surface (FR-19).

    `webhook_secret_ref` is a SEPARATE Secrets Manager reference from `secret_ref`: the
    former is our credential for logging into the ERP, the latter is the credential the
    ERP uses to prove a webhook call came from it. Reusing one secret for both would mean
    a leaked webhook URL (which, for Odoo's shared-secret-in-path scheme, is the ERP admin
    UI's Automation Rule config — not a secret store) also leaks ERP login access. `None`
    until a connection's webhook is onboarded (target-architecture.md 5a: until then it
    silently relies on the reconciliation sweeper).

    `credentials` is a generic, adapter-interpreted bag of *non-secret* connection
    parameters — e.g. Odoo needs `{"database": ..., "username": ...}`; a token-auth ERP
    (NetSuite, ERPNext) might need an account id, or nothing at all here (everything in
    `secret_ref`). This replaced fixed `database`/`username` fields, which forced Odoo's
    login shape onto every future ERP regardless of whether it fit.
    """

    connection_id: ConnectionId
    erp_type: ErpType
    instance_label: str
    base_url: str
    credentials: dict[str, str]
    secret_ref: str
    status: ConnectionStatus = ConnectionStatus.ACTIVE
    webhook_secret_ref: str | None = None

    @property
    def is_active(self) -> bool:
        return self.status is ConnectionStatus.ACTIVE
