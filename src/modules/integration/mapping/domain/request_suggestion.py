"""Suggest which record kinds (and REST paths) to pull live from a new ERP.

The "pull samples live" onboarding step (ADR-0021) asks the operator to type the
sample requests by hand — "orders", "/orders?limit=5" — which only works if they
already know the ERP's API shape. This fills that in: given the ERP's type, label,
base URL, and the canonical fields we're trying to find, ask the LLM for a short list
likely to contain them, with its best guess at the real path for that ERP if it
recognizes it, or a generic REST guess otherwise. The operator still sees and can
edit every suggestion before firing it — this proposes, it never calls out itself.

Pure logic only (prompt + parsing) — same split as `proposal.py`; the LLM call lives
in `infrastructure/request_suggester.py`.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

_ARRAY = re.compile(r"\[.*\]", re.S)
_MAX_SUGGESTIONS = 5
_VALID_METHODS = {"GET", "POST"}


@dataclass(frozen=True)
class SuggestedSampleRequest:
    """One LLM-suggested sample request — the operator reviews and can edit every field
    before anything is actually fired (that still goes through `SampleRequestSpec`, this
    module's only job is to propose a starting point)."""

    label: str
    method: str
    path: str


def build_system_prompt() -> str:
    return """You help an operator onboard a new ERP or e-commerce platform into an \
order-to-cash integration. Given the platform's name/type and the canonical fields we \
need to find on it, suggest a short list of REST API calls that would each pull a \
small SAMPLE of one kind of record (e.g. orders, customers, products) likely to \
contain some of those fields.

Rules:
- `base_url` and `instance_label` identify the actual host. If you know that host's \
real API, use its real relative paths, including any prefix such as "/api/v1". \
A generic "/orders" is only for a host you do not recognize. \
Never invent order, shipment, or invoice paths for a catalog API that only has \
products, categories, or users.
- Every path must include a small limit/page-size so the sample stays small (aim for \
5-10 records), e.g. "/orders?limit=5" or "/orders?page_size=5".
- One call per distinct kind of record. 2-5 calls total, never more.
- `method` is "GET" unless that platform's real API genuinely requires something else \
for a read-only sample query.
- `path` is relative — never include a scheme or hostname, the connection's own \
base_url is used for that.
- Reply with ONLY a JSON array, no prose, no markdown fences. Each element:
  {"label": str, "method": "GET"|"POST", "path": str}
"""


def build_user_prompt(
    erp_type: str, instance_label: str, base_url: str, canonical_fields_csv: str
) -> str:
    return json.dumps(
        {
            "erp_type": erp_type,
            "instance_label": instance_label,
            "base_url": base_url,
            "canonical_fields_csv": canonical_fields_csv,
        }
    )


def parse_suggestions(text: str) -> list[SuggestedSampleRequest]:
    """Raises `ValueError` on a malformed reply so the caller can retry."""
    match = _ARRAY.search(text)
    if not match:
        raise ValueError(f"model did not return a JSON array: {text[:200]!r}")
    result = json.loads(match.group(0))
    suggestions: list[SuggestedSampleRequest] = []
    for item in result[:_MAX_SUGGESTIONS]:
        if not {"label", "method", "path"} <= item.keys():
            raise ValueError(f"malformed suggestion, missing keys: {item}")
        label = str(item["label"]).strip()
        path = str(item["path"]).strip()
        if not label or not path:
            continue
        method = str(item["method"]).strip().upper()
        if method not in _VALID_METHODS:
            method = "GET"
        suggestions.append(SuggestedSampleRequest(label=label, method=method, path=path))
    return suggestions
