"""Shared network-safety helpers for outbound calls to operator-supplied URLs."""

from __future__ import annotations

from .ssrf_guard import UnsafeUrl, validate_outbound_url

__all__ = ["UnsafeUrl", "validate_outbound_url"]
