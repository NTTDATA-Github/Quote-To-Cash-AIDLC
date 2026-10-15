from __future__ import annotations

import json

import pytest

from src.modules.integration.mapping.domain.request_suggestion import (
    SuggestedSampleRequest,
    parse_suggestions,
)


def test_parse_suggestions_extracts_valid_entries() -> None:
    text = json.dumps(
        [
            {"label": "orders", "method": "get", "path": "/orders?limit=5"},
            {"label": "customers", "method": "GET", "path": "/customers?limit=5"},
        ]
    )
    assert parse_suggestions(text) == [
        SuggestedSampleRequest(label="orders", method="GET", path="/orders?limit=5"),
        SuggestedSampleRequest(label="customers", method="GET", path="/customers?limit=5"),
    ]


def test_parse_suggestions_tolerates_surrounding_prose() -> None:
    text = 'Sure, here you go:\n[{"label": "orders", "method": "GET", "path": "/orders"}]\nEnjoy!'
    assert parse_suggestions(text) == [
        SuggestedSampleRequest(label="orders", method="GET", path="/orders")
    ]


def test_parse_suggestions_defaults_an_invalid_method_to_get() -> None:
    text = json.dumps([{"label": "orders", "method": "DELETE", "path": "/orders"}])
    assert parse_suggestions(text)[0].method == "GET"


def test_parse_suggestions_drops_entries_with_a_blank_label_or_path() -> None:
    text = json.dumps(
        [
            {"label": "", "method": "GET", "path": "/orders"},
            {"label": "orders", "method": "GET", "path": "   "},
            {"label": "customers", "method": "GET", "path": "/customers"},
        ]
    )
    assert parse_suggestions(text) == [
        SuggestedSampleRequest(label="customers", method="GET", path="/customers")
    ]


def test_parse_suggestions_caps_at_five() -> None:
    text = json.dumps([{"label": f"kind{i}", "method": "GET", "path": f"/k{i}"} for i in range(10)])
    assert len(parse_suggestions(text)) == 5


def test_parse_suggestions_rejects_a_non_array_reply() -> None:
    with pytest.raises(ValueError):
        parse_suggestions("not json at all")


def test_parse_suggestions_rejects_a_malformed_entry() -> None:
    with pytest.raises(ValueError):
        parse_suggestions(json.dumps([{"label": "orders"}]))
