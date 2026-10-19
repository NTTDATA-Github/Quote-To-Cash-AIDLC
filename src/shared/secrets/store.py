"""Secret resolution behind a port.

A `secret_ref` stored on a connection (or a webhook signing key ref) is resolved to the
actual value here — never stored in plaintext in the DB (SECURITY-12). Local dev uses
env vars; production uses Azure Key Vault (`KeyVaultSecretStore` in `src/shared/secrets/
azure.py` — kept in its own module so importing this port does not pull in the Azure SDK,
which keeps the domain modules framework-free, enforced by import-linter).

Every `secret_ref` up to now was provisioned externally (ops runs `aws secretsmanager
create-secret` by hand, then passes the ref in). Outbound webhook signing secrets are the
first case where the app itself generates the value (so it can show it to the reseller
exactly once), which is why `put_secret` exists — it's a real capability gap this closed,
not a speculative addition.
"""

from __future__ import annotations

import os
from typing import Protocol


class SecretNotFound(Exception):
    pass


class SecretStore(Protocol):
    def get_secret(self, secret_ref: str) -> str: ...
    def put_secret(self, secret_ref: str, value: str) -> None: ...


class EnvSecretStore:
    """Resolves `env:VAR_NAME` (or a bare name) from environment variables."""

    def get_secret(self, secret_ref: str) -> str:
        name = secret_ref.split("env:", 1)[-1]
        value = os.environ.get(name)
        if value is None:
            raise SecretNotFound(secret_ref)
        return value

    def put_secret(self, secret_ref: str, value: str) -> None:
        name = secret_ref.split("env:", 1)[-1]
        os.environ[name] = value
