"""Shared ERP probe: a small stdlib HTTP client that fetches sample records from an ERP
(or just checks an endpoint is reachable), plus its data shapes and port.

Lives in the shared kernel so both `integration.mapping` (onboarding/sample fetch) and
`reference.connections` (test endpoint) can use it without `reference` importing
`integration` — see the import-linter "Reference is a leaf subdomain" contract.
"""

from __future__ import annotations

from .generic import GenericErpProbe
from .models import ProbeSample, SampleRequestSpec
from .port import ErpProbe
from .stub import StubErpProbe

__all__ = [
    "ErpProbe",
    "GenericErpProbe",
    "ProbeSample",
    "SampleRequestSpec",
    "StubErpProbe",
]
