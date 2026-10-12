from __future__ import annotations

import json

import pytest

from src.modules.integration.mapping.domain.proposal import (
    UnsupportedSample,
    extract_sample,
    parse_fields,
    parse_response,
    valid_field_names,
)


def test_parse_fields_tolerates_header_and_blank_lines() -> None:
    fields = parse_fields("field,description\norder_id,The id\n\ncustomer,Who\n")
    assert fields == [
        {"field": "order_id", "description": "The id"},
        {"field": "customer", "description": "Who"},
    ]
    assert valid_field_names("field,description\norder_id,x\ncustomer,y") == {
        "order_id",
        "customer",
    }


def test_extract_sample_csv_truncates_to_header_plus_n_rows() -> None:
    raw = "h1,h2\n" + "\n".join(f"a{i},b{i}" for i in range(50))
    out = extract_sample("export.csv", raw, limit=3)
    assert out.splitlines() == ["h1,h2", "a0,b0", "a1,b1", "a2,b2"]


def test_extract_sample_json_truncates_by_record() -> None:
    raw = json.dumps([{"n": i} for i in range(10)])
    out = extract_sample("export.json", raw, limit=2)
    assert json.loads(out) == [{"n": 0}, {"n": 1}]


def test_extract_sample_rejects_non_array_and_invalid_json() -> None:
    with pytest.raises(UnsupportedSample):
        extract_sample("x.json", '{"not":"a list"}', limit=5)
    with pytest.raises(UnsupportedSample):
        extract_sample("x.json", "{bad json", limit=5)


def test_parse_response_keeps_only_valid_canonical_fields() -> None:
    valid = {"order_id", "customer"}
    text = json.dumps(
        [
            {
                "erp_field": "ORDER_NO",
                "canonical_field": "order_id",
                "sample_data": "1",
                "confidence": 98,
            },
            {
                "erp_field": "RANDOM",
                "canonical_field": "invented",
                "sample_data": "x",
                "confidence": 50,
            },
        ]
    )
    result = parse_response(text, valid)
    assert len(result) == 1
    assert result[0].canonical_field == "order_id"
    assert result[0].confidence == 98


def test_parse_response_extracts_array_embedded_in_prose() -> None:
    entry = '{"erp_field":"C","canonical_field":"customer","sample_data":"Acme","confidence":90}'
    result = parse_response(f"Here you go:\n[{entry}] done", {"customer"})
    assert [e.erp_field for e in result] == ["C"]


def test_parse_response_rejects_out_of_range_confidence_and_missing_keys() -> None:
    with pytest.raises(ValueError, match="confidence"):
        parse_response(
            json.dumps(
                [
                    {
                        "erp_field": "a",
                        "canonical_field": "customer",
                        "sample_data": "x",
                        "confidence": 150,
                    }
                ]
            ),
            {"customer"},
        )
    with pytest.raises(ValueError, match="missing keys"):
        parse_response(
            json.dumps([{"erp_field": "a", "canonical_field": "customer"}]), {"customer"}
        )
    with pytest.raises(ValueError, match="JSON array"):
        parse_response("no array here", {"customer"})
