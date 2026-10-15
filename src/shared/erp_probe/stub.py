"""`StubErpProbe` — deterministic, offline stand-in for an ERP's HTTP API.

Returns a canned sample per request instead of dialing out, so the memory profile (local
dev + tests) runs end to end with no network dependency.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from .models import ProbeSample

if TYPE_CHECKING:
    from src.shared.erp_auth import AuthConfig

    from .models import SampleRequestSpec


class StubErpProbe:
    def fetch_samples(
        self,
        *,
        base_url: str,
        auth: AuthConfig,
        secret_ref: str | None,
        requests: list[SampleRequestSpec],
    ) -> list[ProbeSample]:
        return [
            ProbeSample(
                label=f"{spec.label}.json", text=json.dumps([{"id": "1", "field": spec.label}])
            )
            for spec in requests
        ]
