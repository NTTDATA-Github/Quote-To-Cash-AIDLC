"""Pure mapping-proposal logic: parse the canonical CSV, sample an uploaded export, build
the LLM prompt, and validate the LLM's reply. Stdlib only — no AI SDK, no framework — so
the actual provider call (`infrastructure/llm_proposer.py`) is the only untestable-offline
part, and every rule here (field filtering, confidence bounds, JSON extraction) is unit
tested without a network.

Ported from the former standalone `erp-mapping-service` (`service/samples.py`,
`service/mapping.py`); the prompt and the strict-confidence calibration are unchanged.
"""

from __future__ import annotations

import csv
import io
import json
import re

from .models import MappingEntry

SAMPLE_ROWS = 20

_REQUIRED_KEYS = {"erp_field", "canonical_field", "sample_data", "confidence"}
_ARRAY = re.compile(r"\[.*\]", re.S)


class UnsupportedSample(ValueError):
    """An uploaded sample file was neither usable CSV nor a JSON array of records."""


def parse_fields(csv_text: str) -> list[dict[str, str]]:
    """A 2-column CSV: field, description. Tolerates a header row (first cell literally
    "field") and blank lines; everything else is read as data."""
    rows = [r for r in csv.reader(io.StringIO(csv_text)) if r and r[0].strip()]
    if rows and rows[0][0].strip().lower() == "field":
        rows = rows[1:]
    return [
        {"field": r[0].strip(), "description": r[1].strip() if len(r) > 1 else ""} for r in rows
    ]


def valid_field_names(csv_text: str) -> set[str]:
    return {f["field"] for f in parse_fields(csv_text)}


def extract_sample(filename: str, raw_text: str, limit: int = SAMPLE_ROWS) -> str:
    """Turn one uploaded file into a truncated text sample. CSV is sampled by line
    (header + N rows); JSON by record (first N objects of the array) so truncation never
    cuts a JSON array mid-object and hands the model broken input."""
    if filename.lower().endswith(".json"):
        return _sample_json(raw_text, limit)
    return _sample_csv(raw_text, limit)


def _sample_csv(raw_text: str, limit: int) -> str:
    lines = raw_text.splitlines()
    return "\n".join(lines[: limit + 1])  # header + N data rows


def _sample_json(raw_text: str, limit: int) -> str:
    try:
        data = json.loads(raw_text)
    except json.JSONDecodeError as e:
        raise UnsupportedSample(f"not valid JSON: {e}") from e
    if not isinstance(data, list):
        raise UnsupportedSample("expected a JSON array of records (a list of objects)")
    return json.dumps(data[:limit])


def build_system_prompt(canonical_fields_csv: str) -> str:
    return f"""You map a new ERP's exported field names onto the canonical field list \
below. Use ONLY the fields listed here — never invent one.

{canonical_fields_csv}

Each file under "sample_exports" is either CSV rows or a JSON array of record \
objects — read whichever format it's actually in. Treat every field from every file \
as one combined pool: the same canonical concept may be split across separate files \
(e.g. an order export and a separate invoice export), so map each field to the single \
best canonical field regardless of which file it came from, not file-by-file in \
isolation.

Rules:
- Examine every field from every file, but only include a field in your output if it \
actually maps to one of the canonical fields above. If nothing matches, leave it out \
of the output entirely — the output is a mapping, not a review checklist, so a \
non-match has no row. Never fabricate a value for sample_data that isn't in the \
input, and never invent a canonical field name that isn't in the list above.
- If an ERP column could plausibly map to more than one canonical field, still pick \
the single most likely one and reflect the ambiguity in `confidence` (low), not by \
leaving it unaddressed.
- `confidence` is an integer 0-100, and you must be strict and calibrated, not \
generous:
  - Above 95 is reserved for cases you are 100% sure of: the field name, what it \
  actually represents, AND the sample data all unambiguously point to exactly one \
  canonical field, with no plausible alternative and no guessing from naming \
  convention alone.
  - Below 40 whenever there is real doubt: the ERP field name is generic or \
  abbreviated, the sample data doesn't fully confirm the match, more than one \
  canonical field could plausibly fit, or you are relying on a naming pattern rather \
  than direct evidence (e.g. matching "subsidiary" to a field just because the words \
  look alike, without checking whether they mean the same thing). If your doubt is \
  this deep, consider whether it's really a match at all — maybe it shouldn't be in \
  the output.
  - Use the 40-95 range only for genuine partial evidence — most mappings should NOT \
  cluster in the middle; a lazy "safe" score in the 60s-80s for everything is wrong \
  and defeats the point of this field.
- Reply with ONLY a JSON array, no prose, no markdown fences. Each element:
  {{"erp_field": str, "canonical_field": str, "sample_data": str, "confidence": int}}
"""


def build_user_prompt(erp_name: str, sample_exports: dict[str, str]) -> str:
    return json.dumps({"erp_name": erp_name, "sample_exports": sample_exports})


def parse_response(text: str, valid_fields: set[str]) -> list[MappingEntry]:
    """Parse the model's JSON array into `MappingEntry` rows. A field with no match, or a
    canonical name the model invented that isn't in `valid_fields`, is filtered out — not
    kept as a null row. Raises `ValueError` on a malformed reply so the worker retries."""
    match = _ARRAY.search(text)
    if not match:
        raise ValueError(f"model did not return a JSON array: {text[:200]!r}")
    result = json.loads(match.group(0))
    mapped: list[MappingEntry] = []
    for item in result:
        if not item.keys() >= _REQUIRED_KEYS:
            raise ValueError(f"malformed mapping entry, missing keys: {item}")
        confidence = item["confidence"]
        if (
            not isinstance(confidence, int | float)
            or isinstance(confidence, bool)
            or confidence < 0
            or confidence > 100
        ):
            raise ValueError(f"malformed mapping entry, confidence must be 0-100: {item}")
        canonical_field = item["canonical_field"]
        if canonical_field is None or canonical_field not in valid_fields:
            continue
        mapped.append(
            MappingEntry(
                erp_field=str(item["erp_field"]),
                canonical_field=str(canonical_field),
                sample_data=str(item["sample_data"]),
                confidence=int(confidence),
            )
        )
    return mapped
