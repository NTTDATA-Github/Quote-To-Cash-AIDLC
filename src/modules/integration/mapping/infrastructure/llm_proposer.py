"""`MappingProposer` backed by an injected `LlmClient` (Bedrock in the postgres profile).

No cloud SDK here — boto3 is not allowed inside `src.modules` (the "framework-free"
architecture contract), so the actual provider call lives in `src.shared.llm` and is
injected. This module owns only the mapping-specific orchestration: build the prompt
(from the framework-free `domain/proposal.py`), call the client, parse + validate the
reply, and retry a few times on failure. Model choice is Haiku-class — structured JSON
extraction, not coding.
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

from ..domain.proposal import (
    build_system_prompt,
    build_user_prompt,
    parse_response,
    valid_field_names,
)

if TYPE_CHECKING:
    from ..application.ports import LlmClient
    from ..domain.models import MappingEntry

log = logging.getLogger("mapping-worker")

_MAX_ATTEMPTS = 3


class LlmMappingProposer:
    """`MappingProposer` over any `LlmClient`. Retries on a provider/parse failure with
    backoff; the prompt and strict-confidence calibration live in `domain/proposal.py`."""

    def __init__(self, client: LlmClient) -> None:
        self._client = client

    def propose(
        self, erp_name: str, sample_exports: dict[str, str], canonical_fields_csv: str
    ) -> list[MappingEntry]:
        system = build_system_prompt(canonical_fields_csv)
        user = build_user_prompt(erp_name, sample_exports)
        valid = valid_field_names(canonical_fields_csv)
        last_error: Exception | None = None
        for attempt in range(1, _MAX_ATTEMPTS + 1):
            try:
                return parse_response(self._client.ask(system, user), valid)
            except Exception as e:  # retry any provider/parse failure
                last_error = e
                if attempt < _MAX_ATTEMPTS:
                    time.sleep(2**attempt)
        assert last_error is not None
        raise last_error
