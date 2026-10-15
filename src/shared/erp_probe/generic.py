"""`GenericErpProbe` — makes a small number of authenticated HTTP calls against an ERP,
to fetch sample records (for the mapping proposer) or just to confirm an endpoint is
reachable (the connections "test endpoint" action). Stdlib-only client (same discipline
as `OdooAdapter`): no requests/httpx, no provider SDK.

Declarative auth only (`src.shared.erp_auth`) — anything needing a handshake or a
redirect UI still goes through the manual sample-file upload path
(`MappingService.submit_job`), which stays available regardless.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import TYPE_CHECKING

from src.shared.erp_auth import AppliedAuth, AuthConfig, apply_auth
from src.shared.net import validate_outbound_url

from .models import ProbeSample

if TYPE_CHECKING:
    from src.shared.secrets.store import SecretStore

    from .models import SampleRequestSpec

# A sample is for mapping proposal, not bulk export — cap what we pull into memory/DB.
_MAX_BODY_BYTES = 200_000


def _complete_json_array(body: str) -> str:
    """A capped read can slice a JSON array mid-string. Keep every top-level element
    that fully arrived so the mapping proposer gets valid JSON."""
    text = body.lstrip()
    if not text.startswith("["):
        return body
    try:
        json.loads(text)
        return body
    except json.JSONDecodeError:
        pass
    decoder = json.JSONDecoder()
    idx = 1
    items: list[object] = []
    while idx < len(text):
        while idx < len(text) and text[idx] in " \n\r\t,":
            idx += 1
        if idx >= len(text) or text[idx] == "]":
            break
        try:
            item, end = decoder.raw_decode(text, idx)
        except json.JSONDecodeError:
            break
        items.append(item)
        idx = end
    return json.dumps(items) if items else body


def _detect_extension(content_type: str | None, body: str) -> str:
    """`extract_sample` (mapping's domain/proposal.py) decides CSV vs JSON by filename
    extension — this picks one so a probed response reuses that logic unchanged, instead
    of a new content-sniffing path for the same decision."""
    if content_type and "json" in content_type.lower():
        return "json"
    stripped = body.strip()
    if stripped.startswith("[") or stripped.startswith("{"):
        return "json"
    return "csv"


class GenericErpProbe:
    def __init__(
        self,
        secret_store: SecretStore,
        timeout_seconds: float = 10.0,
        *,
        allow_private_addresses: bool = False,
    ) -> None:
        """`allow_private_addresses` skips the SSRF guard entirely — for local dev only,
        where the ERP being tested (Odoo, the NetSuite mock) is deliberately on
        `localhost`, which the guard correctly treats as unsafe for a real deployment.
        Never set outside a local/offline environment; `composition.py` only turns this
        on from `ERP_PROBE_ALLOW_PRIVATE_ADDRESSES`, which staging/production never set."""
        self._secrets = secret_store
        self._timeout = timeout_seconds
        self._allow_private_addresses = allow_private_addresses

    def fetch_samples(
        self,
        *,
        base_url: str,
        auth: AuthConfig,
        secret_ref: str | None,
        requests: list[SampleRequestSpec],
    ) -> list[ProbeSample]:
        secret = self._secrets.get_secret(secret_ref) if secret_ref else None
        try:
            applied = apply_auth(auth, secret)
        except ValueError as exc:
            return [ProbeSample(label=r.label, error=str(exc)) for r in requests]

        return [self._fetch_one(base_url, applied, spec) for spec in requests]

    def _fetch_one(
        self, base_url: str, applied: AppliedAuth, spec: SampleRequestSpec
    ) -> ProbeSample:
        query = {**spec.query_params, **applied.query_params}
        url = base_url.rstrip("/") + "/" + spec.path.lstrip("/")
        if query:
            url += "?" + urllib.parse.urlencode(query)

        if not self._allow_private_addresses:
            try:
                validate_outbound_url(url)
            except ValueError as exc:
                return ProbeSample(label=spec.label, error=str(exc))

        request = urllib.request.Request(url, method=spec.method.upper(), headers=applied.headers)
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as response:
                raw = response.read(_MAX_BODY_BYTES)
                body = _complete_json_array(raw.decode("utf-8", errors="replace"))
                content_type = response.headers.get("Content-Type")
        except urllib.error.HTTPError as exc:
            return ProbeSample(label=spec.label, error=f"HTTP {exc.code}: {exc.reason}")
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            return ProbeSample(label=spec.label, error=f"cannot reach ERP: {exc}")

        extension = _detect_extension(content_type, body)
        return ProbeSample(label=f"{spec.label}.{extension}", text=body)
