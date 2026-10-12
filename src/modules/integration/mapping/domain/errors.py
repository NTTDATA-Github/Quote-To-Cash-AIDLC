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
