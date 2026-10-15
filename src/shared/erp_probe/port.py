"""The `ErpProbe` port — a small HTTP client that fetches sample records from an ERP.

Kept behind a Protocol so callers (`MappingService`, `ConnectionService`) depend on the
shape, not a concrete client, and tests inject a deterministic stub (`StubErpProbe`).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from src.shared.erp_auth import AuthConfig

    from .models import ProbeSample, SampleRequestSpec


class ErpProbe(Protocol):
    def fetch_samples(
        self,
        *,
        base_url: str,
        auth: AuthConfig,
        secret_ref: str | None,
        requests: list[SampleRequestSpec],
    ) -> list[ProbeSample]:
        """One `ProbeSample` per request, in order — a failed request is a `ProbeSample`
        with `error` set, not an exception, so one bad endpoint doesn't sink the others."""
        ...
