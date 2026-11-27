"""The kind of problem behind a conflict, so repeats group into one thing to fix.

Rules, in order, on the reason code and the ERP's message. The first match wins. Anything no rule
recognises is OTHER: it stays visible, so nothing is quietly lumped into a wrong group.
"""

from __future__ import annotations

from enum import Enum


class ConflictCategory(str, Enum):
    CUSTOMER_ON_HOLD = "CUSTOMER_ON_HOLD"
    PRODUCT_NOT_FOUND = "PRODUCT_NOT_FOUND"
    PRICE_MISMATCH = "PRICE_MISMATCH"
    ADDRESS_PROBLEM = "ADDRESS_PROBLEM"
    DUPLICATE_ORDER = "DUPLICATE_ORDER"
    ERP_UNREACHABLE = "ERP_UNREACHABLE"
    OTHER = "OTHER"


# (category, words that identify it in the ERP's message, lowercase).
_RULES: tuple[tuple[ConflictCategory, tuple[str, ...]], ...] = (
    (
        ConflictCategory.ERP_UNREACHABLE,
        ("timeout", "timed out", "unavailable", "unreachable"),
    ),
    (ConflictCategory.CUSTOMER_ON_HOLD, ("on hold", "credit limit", "blocked", "hold")),
    (ConflictCategory.PRODUCT_NOT_FOUND, ("product", "sku", "item not found", "unknown item")),
    (ConflictCategory.PRICE_MISMATCH, ("price", "pricelist", "discount")),
    (ConflictCategory.ADDRESS_PROBLEM, ("address", "ship-to", "ship to", "postcode", "zip")),
    (ConflictCategory.DUPLICATE_ORDER, ("duplicate", "already exists", "already been")),
)

# Shown to the operator, in plain words. The same text is used for the group headings.
LABELS: dict[ConflictCategory, str] = {
    ConflictCategory.CUSTOMER_ON_HOLD: "Customer on hold in the ERP",
    ConflictCategory.PRODUCT_NOT_FOUND: "Product not found in the ERP",
    ConflictCategory.PRICE_MISMATCH: "Price does not match the ERP",
    ConflictCategory.ADDRESS_PROBLEM: "Shipping address rejected",
    ConflictCategory.DUPLICATE_ORDER: "Order already exists in the ERP",
    ConflictCategory.ERP_UNREACHABLE: "ERP unreachable, still retrying",
    ConflictCategory.OTHER: "Other errors",
}


def classify(reason_code: str, reason: str) -> ConflictCategory:
    text = f"{reason_code} {reason}".lower()
    for category, words in _RULES:
        if any(word in text for word in words):
            return category
    return ConflictCategory.OTHER
