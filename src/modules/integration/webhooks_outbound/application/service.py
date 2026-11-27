"""WebhookEndpointService — register/pause/resume reseller webhook endpoints.

Generates the signing secret itself (unlike `ErpConnection.secret_ref`, which is always
provisioned externally) and returns it once, in the same call, for the UI to show-and-copy.
"""

from __future__ import annotations

import secrets as secret_gen
from typing import TYPE_CHECKING
from urllib.parse import urlparse

from src.shared.erp_auth import AuthType
from src.shared.types import TenantId, WebhookEndpointId, generate_id

from ..domain.errors import WebhookEndpointNotFound
from ..domain.models import WebhookEndpoint

if TYPE_CHECKING:
    from src.shared.secrets import SecretStore

    from .ports import WebhookEndpointRepository


class WebhookEndpointService:
    def __init__(self, repository: WebhookEndpointRepository, secrets: SecretStore) -> None:
        self._repository = repository
        self._secrets = secrets

    def register(
        self,
        *,
        tenant_id: TenantId,
        name: str,
        url: str,
        event_types: frozenset[str] | None,
        auth_type: AuthType = AuthType.NONE,
        auth_params: dict[str, str] | None = None,
        auth_secret: str | None = None,
    ) -> tuple[WebhookEndpoint, str]:
        """Returns the endpoint and its signing secret (shown once). `auth_secret` is the
        credential we send to the receiver; it is stored separately and never returned."""
        # Everything is checked before anything is stored, so a rejected request leaves no
        # secret behind.
        if not name.strip():
            raise ValueError("name must not be blank")
        parsed = urlparse(url.strip())
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            raise ValueError(f"url must be a full http(s) URL, got {url!r}")
        params = dict(auth_params or {})
        if auth_type is not AuthType.NONE and not auth_secret:
            raise ValueError(f"{auth_type.value} needs a secret")
        if auth_type is AuthType.BASIC and not params.get("username", "").strip():
            raise ValueError("basic authentication needs a username")

        endpoint_id = WebhookEndpointId(generate_id("whep"))
        secret_ref = f"webhook-endpoint/{endpoint_id}"
        raw_secret = f"whsec_{secret_gen.token_hex(20)}"
        self._secrets.put_secret(secret_ref, raw_secret)
        auth_secret_ref = None
        if auth_type is not AuthType.NONE:
            auth_secret_ref = f"webhook-endpoint-auth/{endpoint_id}"
            self._secrets.put_secret(auth_secret_ref, auth_secret or "")

        endpoint = WebhookEndpoint(
            endpoint_id=endpoint_id,
            tenant_id=tenant_id,
            name=name,
            url=url,
            secret_ref=secret_ref,
            event_types=event_types,
            is_active=True,
            auth_type=auth_type,
            auth_params=params,
            auth_secret_ref=auth_secret_ref,
        )
        self._repository.add(endpoint)
        return endpoint, raw_secret

    def pause(self, endpoint_id: WebhookEndpointId, *, tenant_id: TenantId) -> WebhookEndpoint:
        endpoint = self._get_or_raise(endpoint_id, tenant_id)
        endpoint.is_active = False
        self._repository.update(endpoint)
        return endpoint

    def resume(self, endpoint_id: WebhookEndpointId, *, tenant_id: TenantId) -> WebhookEndpoint:
        endpoint = self._get_or_raise(endpoint_id, tenant_id)
        endpoint.is_active = True
        self._repository.update(endpoint)
        return endpoint

    def _get_or_raise(self, endpoint_id: WebhookEndpointId, tenant_id: TenantId) -> WebhookEndpoint:
        # tenant_id checked here, not just "does the row exist" — otherwise any
        # authenticated reseller could pause/resume another tenant's endpoint by ID.
        # Wrong tenant reads as not-found (fail-closed), same convention as the
        # projection store's tenant-scoped reads.
        endpoint = self._repository.get(endpoint_id)
        if endpoint is None or endpoint.tenant_id != tenant_id:
            raise WebhookEndpointNotFound(str(endpoint_id))
        return endpoint
