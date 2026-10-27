from __future__ import annotations

import pytest

from src.modules.integration.conflicts.domain.categories import LABELS, ConflictCategory, classify


@pytest.mark.parametrize(
    ("reason_code", "reason", "expected"),
    [
        (
            "erp_rejected",
            "Customer on hold in the ERP (demo rule)",
            ConflictCategory.CUSTOMER_ON_HOLD,
        ),
        ("erp_rejected", "Credit limit exceeded", ConflictCategory.CUSTOMER_ON_HOLD),
        ("erp_rejected", "Unknown product SKU ANVIL-9", ConflictCategory.PRODUCT_NOT_FOUND),
        ("erp_rejected", "Unit price differs from the price list", ConflictCategory.PRICE_MISMATCH),
        ("erp_rejected", "Ship-to address is incomplete", ConflictCategory.ADDRESS_PROBLEM),
        ("erp_rejected", "Order already exists", ConflictCategory.DUPLICATE_ORDER),
        ("erp_unavailable", "timeout", ConflictCategory.ERP_UNREACHABLE),
        (
            "connection_unavailable",
            "target ERP connection unavailable",
            ConflictCategory.ERP_UNREACHABLE,
        ),
        ("erp_rejected", "something nobody has seen before", ConflictCategory.OTHER),
    ],
)
def test_each_message_lands_in_its_category(
    reason_code: str, reason: str, expected: ConflictCategory
) -> None:
    assert classify(reason_code, reason) is expected


def test_a_connection_on_hold_is_a_hold_not_an_unreachable_erp() -> None:
    assert (
        classify("erp_rejected", "Customer's connection on hold")
        is ConflictCategory.CUSTOMER_ON_HOLD
    )


def test_every_category_has_a_plain_label() -> None:
    assert set(LABELS) == set(ConflictCategory)


def test_each_demo_erp_message_lands_in_the_cause_the_demo_intends() -> None:
    from src.modules.integration.erp.infrastructure.demo_adapter import DEMO_REJECTIONS

    expected = {
        "1": ConflictCategory.CUSTOMER_ON_HOLD,
        "3": ConflictCategory.PRODUCT_NOT_FOUND,
        "4": ConflictCategory.PRICE_MISMATCH,
        "5": ConflictCategory.ADDRESS_PROBLEM,
        "6": ConflictCategory.DUPLICATE_ORDER,
        "7": ConflictCategory.OTHER,
    }
    for customer, category in expected.items():
        assert classify("erp_rejected", DEMO_REJECTIONS[customer]) is category, customer
