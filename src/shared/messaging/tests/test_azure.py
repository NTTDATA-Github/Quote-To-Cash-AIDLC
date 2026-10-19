"""Unit tests for the Service Bus adapter (ADR-0023).

`azure-servicebus` isn't installed in every dev environment yet (it's a new dependency —
see pyproject.toml); skip rather than fail where it's absent, using `pytest.importorskip`.
Once installed, these run for real against the SDK's own message/session types, with no
mocking of `azure.servicebus` itself, only of the network-touching `ServiceBusClient`.
"""

from __future__ import annotations

import pytest

from src.shared.eventsourcing import StoredEvent
from src.shared.messaging.azure import ServiceBusConsumerRunner, ServiceBusPublisher

pytest.importorskip("azure.servicebus")

from datetime import UTC, datetime  # noqa: E402


def _event(event_type: str = "OrderSubmitted", stream_id: str = "ord_1") -> StoredEvent:
    return StoredEvent(
        stream_id=stream_id,
        aggregate_type="Order",
        version=1,
        event_type=event_type,
        event_id="evt_1",
        occurred_at=datetime.now(UTC),
        payload={},
        tenant_id="tnt_demo",
        correlation_id=None,
    )


class _FakeSender:
    def __init__(self) -> None:
        self.sent: list[object] = []

    def __enter__(self) -> _FakeSender:
        return self

    def __exit__(self, *_exc: object) -> None:
        return None

    def send_messages(self, message: object) -> None:
        self.sent.append(message)


class _FakeClient:
    def __init__(self) -> None:
        self.sender = _FakeSender()

    def get_topic_sender(self, topic_name: str) -> _FakeSender:
        self.topic_name = topic_name
        return self.sender


def test_publish_sets_session_id_and_event_type_property() -> None:
    client = _FakeClient()
    publisher = ServiceBusPublisher(
        "ns.servicebus.windows.net", "platform-domain-events", client=client
    )

    publisher.publish([_event(stream_id="ord_42", event_type="OrderSubmitted")])

    assert client.topic_name == "platform-domain-events"
    (message,) = client.sender.sent
    assert message.session_id == "ord_42"
    assert message.application_properties == {"eventType": "OrderSubmitted"}


class _FakeReceiver:
    def __init__(self, messages: list[object]) -> None:
        self._messages = messages
        self.completed: list[object] = []
        self.abandoned: list[object] = []

    def __enter__(self) -> _FakeReceiver:
        return self

    def __exit__(self, *_exc: object) -> None:
        return None

    def receive_messages(self, max_wait_time: float) -> list[object]:
        return self._messages

    def complete_message(self, message: object) -> None:
        self.completed.append(message)

    def abandon_message(self, message: object) -> None:
        self.abandoned.append(message)


class _FakeClientWithReceiver:
    def __init__(self, receiver: _FakeReceiver) -> None:
        self._receiver = receiver

    def get_subscription_receiver(self, **_kwargs: object) -> _FakeReceiver:
        return self._receiver


def test_poll_once_completes_the_message_on_handler_success() -> None:
    from src.shared.messaging.envelope import to_json

    seen: list[str] = []
    message = to_json(_event())
    receiver = _FakeReceiver([message])
    runner = ServiceBusConsumerRunner(
        "ns.servicebus.windows.net",
        "platform-domain-events",
        "order-processing",
        lambda event: seen.append(event.event_id),
        client=_FakeClientWithReceiver(receiver),
    )

    count = runner.poll_once()

    assert count == 1
    assert seen == ["evt_1"]
    assert receiver.completed == [message]
    assert receiver.abandoned == []


def test_poll_once_returns_zero_when_no_session_is_ready() -> None:
    from azure.servicebus.exceptions import ServiceBusError

    class _NoSessionClient:
        def get_subscription_receiver(self, **_kwargs: object) -> None:
            raise ServiceBusError("no session available")

    runner = ServiceBusConsumerRunner(
        "ns.servicebus.windows.net",
        "platform-domain-events",
        "order-processing",
        lambda _event: None,
        client=_NoSessionClient(),
    )

    assert runner.poll_once() == 0


def test_poll_once_returns_zero_when_no_session_is_ready_on_enter() -> None:
    """The real production failure mode (confirmed against a live deployment): the SDK
    doesn't raise OperationTimeoutError from get_subscription_receiver() itself (that just
    builds a lazy object) -- it raises from __enter__, when the AMQP open actually runs.
    A try/except around construction only (not around `with receiver:` too) let this
    crash the consumer thread on every empty poll instead of returning 0."""
    from azure.servicebus.exceptions import OperationTimeoutError

    class _ReceiverThatTimesOutOnEnter:
        def __enter__(self) -> None:
            raise OperationTimeoutError()

        def __exit__(self, *_exc: object) -> None:
            return None

    class _ClientWithEnterFailure:
        def get_subscription_receiver(self, **_kwargs: object) -> _ReceiverThatTimesOutOnEnter:
            return _ReceiverThatTimesOutOnEnter()

    runner = ServiceBusConsumerRunner(
        "ns.servicebus.windows.net",
        "platform-domain-events",
        "order-processing",
        lambda _event: None,
        client=_ClientWithEnterFailure(),
    )

    assert runner.poll_once() == 0


def test_poll_once_abandons_the_message_on_handler_failure() -> None:
    from src.shared.messaging.envelope import to_json

    message = to_json(_event())
    receiver = _FakeReceiver([message])

    def failing_handler(_event: StoredEvent) -> None:
        raise RuntimeError("boom")

    runner = ServiceBusConsumerRunner(
        "ns.servicebus.windows.net",
        "platform-domain-events",
        "order-processing",
        failing_handler,
        client=_FakeClientWithReceiver(receiver),
    )

    count = runner.poll_once()

    assert count == 1
    assert receiver.abandoned == [message]
    assert receiver.completed == []
