"""Connection domain model."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.shared.types import ConnectionId


def normalize_erp_type(value: str) -> str:
    """The one place `erp_type` is canonicalized (ADR-0021) — same input always compares
    equal regardless of how an operator typed it, so "Shopify" and "shopify" are the same
    ERP for the dedupe check in `MappingService` (ADR-0022), not two accidental ones."""
    return value.strip().upper()


class ConnectionStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"


@dataclass
class ErpConnection:
    """One ERP instance (e.g. one Odoo database). Operator-only identity.

    `erp_type` is a normalized string, not a closed enum (ADR-0021) — a connection can
    exist for a brand-new ERP before any code has been written for it. Whether delivery
    actually works for this type is a separate, derived fact (`hasAdapter`, read from the
    adapter registry at query time — see `composition.py`'s `has_adapter`), never stored
    here.

    `secret_ref` is a secret store reference — never the raw credential (SECURITY-12).
    `instance_label` is operator-only and must never reach a reseller surface (FR-19).

    `webhook_secret_ref` is a SEPARATE secret store reference from `secret_ref`: the
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
    login shape onto every future ERP regardless of whether it fit (ADR-0012).

    `auth_type` (ADR-0021) is read only by the generic onboarding probe for a connection
    that has no adapter yet — one of `src.shared.erp_auth.AuthType`'s values, interpreted
    against this same `credentials` bag plus the resolved secret. Once a real adapter
    exists for this `erp_type`, the adapter owns its own auth logic and this field is
    simply never read again; it defaults to `"NONE"` for every connection that was never
    probed this way (including every connection created before this field existed).
    """

    connection_id: ConnectionId
    erp_type: str
    instance_label: str
    base_url: str
    credentials: dict[str, str]
    secret_ref: str
    status: ConnectionStatus = ConnectionStatus.ACTIVE
    webhook_secret_ref: str | None = None
    auth_type: str = "NONE"

    @property
    def is_active(self) -> bool:
        return self.status is ConnectionStatus.ACTIVE
