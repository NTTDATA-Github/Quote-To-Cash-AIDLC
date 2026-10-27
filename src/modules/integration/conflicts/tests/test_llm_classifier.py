from __future__ import annotations

from src.modules.integration.conflicts.domain.categories import ConflictCategory
from src.modules.integration.conflicts.infrastructure.llm_classifier import (
    SYSTEM_PROMPT,
    LlmCauseClassifier,
    UnavailableCauseClassifier,
)


class _Client:
    def __init__(self, answer: str) -> None:
        self.answer = answer
        self.calls = 0

    def ask(self, system: str, user: str, max_tokens: int = 0) -> str:
        self.calls += 1
        return self.answer


def test_a_known_cause_id_is_returned() -> None:
    client = _Client(" ADDRESS_PROBLEM. ")
    assert (
        LlmCauseClassifier(lambda: client).classify("0x4F2 bad consignee")
        is ConflictCategory.ADDRESS_PROBLEM
    )


def test_an_answer_outside_the_list_is_discarded() -> None:
    client = _Client("The customer is probably on hold")
    assert LlmCauseClassifier(lambda: client).classify("0x4F2") is None


def test_the_same_message_is_asked_once() -> None:
    client = _Client("OTHER")
    classifier = LlmCauseClassifier(lambda: client)
    classifier.classify("0x4F2")
    classifier.classify("0x4F2")
    assert client.calls == 1


def test_a_failed_call_is_not_cached_and_returns_nothing() -> None:
    class _Failing:
        calls = 0

        def ask(self, system: str, user: str, max_tokens: int = 0) -> str:
            self.calls += 1
            raise RuntimeError("provider down")

    client = _Failing()
    classifier = LlmCauseClassifier(lambda: client)
    assert classifier.classify("0x4F2") is None
    assert classifier.classify("0x4F2") is None
    assert client.calls == 2


def test_the_prompt_lists_every_cause_except_other() -> None:
    assert "CUSTOMER_ON_HOLD" in SYSTEM_PROMPT
    assert "ERP_UNREACHABLE" in SYSTEM_PROMPT


def test_without_a_provider_nothing_is_suggested() -> None:
    assert UnavailableCauseClassifier().classify("0x4F2") is None


class _Suggests:
    def __init__(self, answer: ConflictCategory | None) -> None:
        self.answer = answer
        self.asked: list[str] = []

    def classify(self, message: str) -> ConflictCategory | None:
        self.asked.append(message)
        return self.answer


def test_a_rule_that_recognises_the_message_wins_and_the_model_is_not_asked() -> None:
    from src.modules.integration.conflicts.application.causes import cause_of

    classifier = _Suggests(ConflictCategory.PRICE_MISMATCH)
    assert cause_of("erp_rejected", "Customer on hold", classifier) == (
        ConflictCategory.CUSTOMER_ON_HOLD,
        "RULE",
    )
    assert classifier.asked == []


def test_an_unrecognised_message_takes_the_models_suggestion() -> None:
    from src.modules.integration.conflicts.application.causes import cause_of

    assert cause_of("erp_rejected", "0x4F2", _Suggests(ConflictCategory.ADDRESS_PROBLEM)) == (
        ConflictCategory.ADDRESS_PROBLEM,
        "AI",
    )


def test_an_unrecognised_message_with_no_suggestion_stays_other() -> None:
    from src.modules.integration.conflicts.application.causes import cause_of

    assert cause_of("erp_rejected", "0x4F2", _Suggests(None)) == (
        ConflictCategory.OTHER,
        "UNRECOGNISED",
    )


def test_the_model_answering_other_is_not_reported_as_an_ai_cause() -> None:
    from src.modules.integration.conflicts.application.causes import cause_of

    assert cause_of("erp_rejected", "0x4F2", _Suggests(ConflictCategory.OTHER)) == (
        ConflictCategory.OTHER,
        "UNRECOGNISED",
    )
