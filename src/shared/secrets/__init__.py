"""Secret store port + implementations.

Implementations: `KeyVaultSecretStore` (Azure, in `.azure`, imported by the composition
root) and `EnvSecretStore` (tests/local). Adapters that pull in a cloud SDK stay out of
this package's public surface, which the "domain is framework-free" import-linter
contract requires.
"""

from __future__ import annotations

from .store import EnvSecretStore, SecretNotFound, SecretStore

__all__ = ["EnvSecretStore", "SecretNotFound", "SecretStore"]
