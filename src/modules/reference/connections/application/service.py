"""ConnectionService — register and read ERP connections (operator-facing)."""

from __future__ import annotations

from typing import TYPE_CHECKING
from urllib.parse import urlparse

from src.shared.erp_auth import AuthConfig, AuthType
from src.shared.erp_probe import SampleRequestSpec
from src.shared.messaging.facts import FactPublisher, make_fact
from src.shared.types import ConnectionId, generate_id

from ..domain.errors import ConnectionNotFound
from ..domain.events import CONNECTION_PAUSED, CONNECTION_REGISTERED, CONNECTION_RESUMED
from ..domain.models import ConnectionStatus, ErpConnection, normalize_erp_type

if TYPE_CHECKING:
    from src.shared.erp_probe import ErpProbe, ProbeSample
    from src.shared.secrets import SecretStore

    from .ports import ConnectionRepository


class ConnectionService:
    def __init__(
        self,
        repository: ConnectionRepository,
        facts: FactPublisher,
        secrets: SecretStore,
        probe: ErpProbe,
    ) -> None:
        self._repository = repository
        self._facts = facts
        self._secrets = secrets
        self._probe = probe

    def register(
        self,
        *,
        erp_type: str,
        instance_label: str,
        base_url: str,
        credentials: dict[str, str],
        secret: str | None,
        auth_type: str = "NONE",
        webhook_secret_ref: str | None = None,
    ) -> ErpConnection:
        """`secret` is the raw credential (password/API key/token) — generated into a
        Secrets Manager reference here, same discipline as `WebhookEndpointService`
        (ADR-0021); the operator never hand-pastes a `secret_ref`. `auth_type="NONE"`
        (the only case with nothing to protect) skips Secrets Manager entirely rather
        than writing an empty value it would reject.

        Validates the free-typed fields a typo most often lands in: a connection with a
        blank label, a blank erp_type, or a base_url that isn't actually a URL would
        otherwise sit silently until the first probe or delivery fails against it."""
        if not instance_label.strip():
            raise ValueError("instance_label must not be blank")
        if not normalize_erp_type(erp_type):
            raise ValueError("erp_type must not be blank")
        parsed = urlparse(base_url.strip())
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            raise ValueError(f"base_url must be a full http(s) URL, got {base_url!r}")
        if auth_type not in AuthType.__members__:
            raise ValueError(f"unknown auth_type {auth_type!r}")
        connection_id = ConnectionId(generate_id("conn"))
        secret_ref = ""
        if secret:
            secret_ref = f"erp-connection/{connection_id}"
            self._secrets.put_secret(secret_ref, secret)
        connection = ErpConnection(
            connection_id=connection_id,
            erp_type=normalize_erp_type(erp_type),
            instance_label=instance_label,
            base_url=base_url,
            credentials=credentials,
            secret_ref=secret_ref,
            status=ConnectionStatus.ACTIVE,
            webhook_secret_ref=webhook_secret_ref,
            auth_type=auth_type,
        )
        self._repository.add(connection)
        self._publish(connection, CONNECTION_REGISTERED)
        return connection

    def get(self, connection_id: ConnectionId) -> ErpConnection | None:
        return self._repository.get(connection_id)

    def test_endpoint(self, connection_id: ConnectionId, *, path: str = "") -> ProbeSample:
        """A single reachability+auth check against this connection's `base_url`, using
        its stored `auth_type`/`credentials`/`secret_ref` (ADR-0021) — nothing retyped.

        Unlike `MappingService.probe_samples` (which gates on mapping *eligibility*), this
        works for any connection regardless of whether its `erp_type` already has an
        adapter — it answers only "can we reach it, does the auth work", so the operator
        can confirm a connection before (or after) it is used anywhere. The result is a
        `ProbeSample` with `error` set on failure, never an exception, so the caller
        renders the ERP's own message instead of a 500."""
        connection = self._repository.get(connection_id)
        if connection is None:
            raise ConnectionNotFound(str(connection_id))
        auth = AuthConfig(
            auth_type=AuthType(connection.auth_type), params=dict(connection.credentials)
        )
        [sample] = self._probe.fetch_samples(
            base_url=connection.base_url,
            auth=auth,
            secret_ref=connection.secret_ref or None,
            requests=[SampleRequestSpec(label="test", path=path)],
        )
        return sample

    def pause(self, connection_id: ConnectionId) -> ErpConnection:
        """Stops new deliveries being routed here (`ConnectionsResolver.resolve` only
        returns active connections) without deleting anything it's referenced by."""
        connection = self._repository.get(connection_id)
        if connection is None:
            raise ConnectionNotFound(str(connection_id))
        connection.status = ConnectionStatus.PAUSED
        self._repository.update(connection)
        self._publish(connection, CONNECTION_PAUSED)
        return connection

    def resume(self, connection_id: ConnectionId) -> ErpConnection:
        connection = self._repository.get(connection_id)
        if connection is None:
            raise ConnectionNotFound(str(connection_id))
        connection.status = ConnectionStatus.ACTIVE
        self._repository.update(connection)
        self._publish(connection, CONNECTION_RESUMED)
        return connection

    def _publish(self, connection: ErpConnection, event_type: str) -> None:
        # Never the secret refs — a fact is a notification other domains may log/inspect,
        # not a place to leak credential pointers.
        self._facts.publish(
            make_fact(
                stream_id=str(connection.connection_id),
                aggregate_type="Connection",
                event_type=event_type,
                payload={
                    "connection_id": str(connection.connection_id),
                    "erp_type": connection.erp_type,
                    "instance_label": connection.instance_label,
                    "status": connection.status.value,
                },
            )
        )
