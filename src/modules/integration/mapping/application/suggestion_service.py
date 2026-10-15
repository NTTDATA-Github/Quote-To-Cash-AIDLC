"""SampleRequestSuggestionService — the LLM call `MappingService` deliberately excludes
(see its module docstring). Kept separate so a provider call never sneaks into the
service that governs job eligibility; this only ever reads through it, never writes.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from src.shared.erp_probe.models import SampleRequestSpec

if TYPE_CHECKING:
    from ..domain.request_suggestion import SuggestedSampleRequest
    from .ports import SampleRequestSuggester
    from .service import MappingService


class SampleRequestSuggestionService:
    def __init__(self, mapping_service: MappingService, suggester: SampleRequestSuggester) -> None:
        self._mapping_service = mapping_service
        self._suggester = suggester

    def suggest(
        self,
        *,
        connection_id: str,
        schema_name: str | None = None,
        canonical_fields_csv: str | None = None,
    ) -> list[SuggestedSampleRequest]:
        connection = self._mapping_service.get_eligible_connection(connection_id)
        resolved_csv = self._mapping_service.resolve_canonical_fields(
            schema_name, canonical_fields_csv
        )
        suggested = self._suggester.suggest(
            connection.erp_type, connection.instance_label, connection.base_url, resolved_csv
        )
        probed = self._mapping_service.probe_samples(
            connection_id=connection_id,
            requests=[
                SampleRequestSpec(label=s.label, method=s.method, path=s.path) for s in suggested
            ],
        )
        kept = [s for s, sample in zip(suggested, probed, strict=False) if sample.error is None]
        return kept or suggested
