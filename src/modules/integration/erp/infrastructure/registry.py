"""ERP adapter registry — the one place a new ERP integration is wired in.

To add a new ERP:
  1. Implement `ErpAdapter` (`submit`/`fetch_status`/`cancel`) in a new
     `infrastructure/<erp>_adapter.py`, following `odoo_adapter.py`'s shape (stdlib-only
     HTTP, explicit timeouts, transient/terminal error classification).
  2. Register its native-status mapping in `domain/status_mapping.py` (`STATUS_MAPPERS`).
  3. Add one line to `build_adapter_registry` below.
  4. Add the ERP type to `ErpType` (`connections/domain/models.py`).
No other file needs to change — `composition.py` resolves adapters through this
registry regardless of how many ERP types are registered.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .netsuite_adapter import NetSuiteAdapter
from .odoo_adapter import OdooAdapter

if TYPE_CHECKING:
    from src.shared.config import Settings

    from ..application.ports import ErpAdapter


def build_adapter_registry(settings: Settings) -> dict[str, ErpAdapter]:
    """One real adapter instance per known ERP type, built once at composition time
    (not per-call — adapters are stateless enough to share, and this avoids
    reconstructing an HTTP-client-equivalent on every delivery/reconcile call)."""
    return {
        "ODOO": OdooAdapter(timeout_seconds=settings.erp_odoo_timeout_seconds),
        "NETSUITE": NetSuiteAdapter(timeout_seconds=settings.erp_netsuite_timeout_seconds),
    }
