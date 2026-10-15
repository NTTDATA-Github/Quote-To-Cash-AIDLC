"""Probe data shapes — plain, framework-free dataclasses.

A `SampleRequestSpec` is one HTTP call to make against an ERP; a `ProbeSample` is its
outcome. These live in the shared kernel (not inside `integration.mapping`) because both
the mapping onboarding flow (`integration`) and the connections "test endpoint" action
(`reference`) depend on them, and `reference` must not import `integration` (see the
import-linter "Reference is a leaf subdomain" contract).
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class SampleRequestSpec:
    """One HTTP call to make against an ERP (e.g. during onboarding, to pull a sample of
    one kind of record like "orders"). `path` is appended to the connection's base_url."""

    label: str
    method: str = "GET"
    path: str = ""
    query_params: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class ProbeSample:
    """One `SampleRequestSpec`'s outcome. Exactly one of `text`/`error` is set — a failed
    request doesn't sink the others (see `GenericErpProbe.fetch_samples`)."""

    label: str
    text: str | None = None
    error: str | None = None
