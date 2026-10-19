"""HMAC-SHA256 webhook signature (pure).

Constant-time comparison prevents timing attacks. The signing secret is per-connection
and resolved from the secret store at the edge.
"""

from __future__ import annotations

import hashlib
import hmac


def compute_signature(secret: str, body: bytes) -> str:
    return hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()


def verify_signature(secret: str, body: bytes, provided_signature: str) -> bool:
    expected = compute_signature(secret, body)
    return hmac.compare_digest(expected, provided_signature or "")


def verify_shared_secret(secret: str, provided: str) -> bool:
    """Shared-secret-in-path scheme (Odoo): the caller supplies the secret itself, not a
    signature over the body — Odoo Automation Rules can only POST to a URL, they can't
    compute an HMAC. Still constant-time, for the same timing-attack reason as above."""
    return hmac.compare_digest(secret, provided or "")
