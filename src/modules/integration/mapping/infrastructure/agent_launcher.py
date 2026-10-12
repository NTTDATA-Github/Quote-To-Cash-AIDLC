"""`AdapterRunLauncher` over HTTP — hands an approved mapping to `erp-agent-service`.

That service stays separate (it shells out to `git`/`claude` on its host to implement the
adapter and open a PR), so this is a plain HTTP client, never a Python import of it. Uses
`httpx`, the same client the outbound-webhook sender uses. Its API:

    POST /runs          {"erp_name": ..., "mapping": [ {erp_field, canonical_field,
                         sample_data, confidence}, ... ]} -> {"run_id": ..., "status": ...}
    GET  /runs/{run_id} -> {"status": "DONE"|"FAILED"|"PENDING"|"PROCESSING",
                            "result": {"branch": ..., "pr_url": ...}, "error": ...}
"""

from __future__ import annotations

from dataclasses import asdict
from typing import TYPE_CHECKING

import httpx

from ..domain.models import AdapterRunResult

if TYPE_CHECKING:
    from ..domain.models import MappingEntry


class HttpAdapterRunLauncher:
    def __init__(self, base_url: str, timeout_seconds: float = 15.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout_seconds

    def launch(self, erp_name: str, mapping: list[MappingEntry]) -> str:
        payload = {"erp_name": erp_name, "mapping": [asdict(entry) for entry in mapping]}
        response = httpx.post(f"{self._base_url}/runs", json=payload, timeout=self._timeout)
        response.raise_for_status()
        return str(response.json()["run_id"])

    def get_run(self, run_id: str) -> AdapterRunResult:
        response = httpx.get(f"{self._base_url}/runs/{run_id}", timeout=self._timeout)
        response.raise_for_status()
        body = response.json()
        result = body.get("result") or {}
        return AdapterRunResult(
            status=str(body.get("status", "PENDING")),
            branch=result.get("branch"),
            pr_url=result.get("pr_url"),
            error=body.get("error"),
        )
