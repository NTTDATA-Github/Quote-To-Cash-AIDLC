"""Mapping-proposer domain errors."""

from __future__ import annotations


class CanonicalSchemaNotFound(Exception):
    """A job referenced a schema name that isn't registered."""


class EmptyCanonicalSchema(Exception):
    """The supplied CSV had no `field` rows — nothing to map onto."""


class MappingJobNotFound(Exception):
    """A referenced mapping job does not exist."""


class MappingNotReady(Exception):
    """Tried to approve a job whose mapping isn't DONE yet (still running, or FAILED)."""


class NoCanonicalFields(Exception):
    """submit_job got neither a registered schema name nor an inline CSV."""


class ProbeFailed(Exception):
    """One or more sample requests against a new ERP failed (bad URL, auth, timeout) —
    distinct from an LLM proposal failure, since the fix is different (check the
    connection details, not the mapping)."""


class ConnectionNotFound(Exception):
    """A mapping submission referenced a connection id that doesn't exist."""


class ErpTypeNotEligible(Exception):
    """ADR-0022: this connection's `erp_type` already has a working adapter, or already
    has a pending/approved mapping job — submitting another would generate a redundant
    adapter PR for an ERP that's already covered (or already being covered)."""
