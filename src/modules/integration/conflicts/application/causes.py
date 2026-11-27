"""The cause shown for a conflict: the rules first, then an AI suggestion for what they missed."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..domain.categories import ConflictCategory, classify

if TYPE_CHECKING:
    from .ports import CauseClassifier


def cause_of(
    reason_code: str, reason: str, classifier: CauseClassifier
) -> tuple[ConflictCategory, str]:
    """Returns (cause, source). Source is RULE when a rule recognised the message, AI when the model
    suggested a cause, and UNRECOGNISED when neither could say. The model is only asked when the
    rules put the message in OTHER."""
    by_rule = classify(reason_code, reason)
    if by_rule is not ConflictCategory.OTHER:
        return by_rule, "RULE"
    suggested = classifier.classify(reason)
    # OTHER from the model means it had no suggestion, so it is not an AI cause.
    if suggested is not None and suggested is not ConflictCategory.OTHER:
        return suggested, "AI"
    return ConflictCategory.OTHER, "UNRECOGNISED"
