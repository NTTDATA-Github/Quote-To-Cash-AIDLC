"""`SampleRequestSuggester` backed by an injected `LlmClient` (Bedrock in the postgres
profile) — same split as `llm_proposer.py`: the prompt/parsing is framework-free
(`domain/request_suggestion.py`), only the provider call and its retries live here.
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

from ..domain.request_suggestion import build_system_prompt, build_user_prompt, parse_suggestions

if TYPE_CHECKING:
    from ..application.ports import LlmClient
    from ..domain.request_suggestion import SuggestedSampleRequest

log = logging.getLogger("mapping-worker")

_MAX_ATTEMPTS = 3


class LlmSampleRequestSuggester:
    def __init__(self, client: LlmClient) -> None:
        self._client = client

    def suggest(
        self, erp_type: str, instance_label: str, base_url: str, canonical_fields_csv: str
    ) -> list[SuggestedSampleRequest]:
        system = build_system_prompt()
        user = build_user_prompt(erp_type, instance_label, base_url, canonical_fields_csv)
        last_error: Exception | None = None
        for attempt in range(1, _MAX_ATTEMPTS + 1):
            try:
                return parse_suggestions(self._client.ask(system, user))
            except Exception as e:  # retry any provider/parse failure
                last_error = e
                if attempt < _MAX_ATTEMPTS:
                    time.sleep(2**attempt)
        assert last_error is not None
        raise last_error
