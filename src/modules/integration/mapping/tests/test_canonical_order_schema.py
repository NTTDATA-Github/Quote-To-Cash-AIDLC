from __future__ import annotations

from src.modules.integration.mapping.domain.canonical_order_schema import (
    build_canonical_order_fields,
    build_canonical_order_fields_csv,
)


def test_build_canonical_order_fields_covers_known_fields_with_humanized_descriptions() -> None:
    fields = dict(build_canonical_order_fields())
    assert fields["product_key"] == "Product Key"
    assert fields["erp_order_id"] == "ERP Order ID"
    assert fields["carrier"] == "Carrier"
    assert "lines" not in fields  # nested record, not a flat field


def test_build_canonical_order_fields_has_no_duplicates() -> None:
    names = [name for name, _ in build_canonical_order_fields()]
    assert len(names) == len(set(names))


def test_build_canonical_order_fields_csv_is_parseable_two_column_csv() -> None:
    csv_text = build_canonical_order_fields_csv()
    lines = csv_text.strip().splitlines()
    assert lines[0] == "field,description"
    assert all(len(line.split(",", 1)) == 2 for line in lines[1:])
