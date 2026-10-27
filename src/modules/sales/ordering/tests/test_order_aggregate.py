from __future__ import annotations

from decimal import Decimal

import pytest

from src.modules.sales.ordering.domain.aggregate import Order
from src.modules.sales.ordering.domain.errors import OrderInvalidTransition
from src.modules.sales.ordering.domain.models import (
    KIND_LICENSE,
    KIND_PHYSICAL,
    DeliveryStatus,
    FulfillmentStatus,
    InvoiceStatus,
    OrderLine,
    OrderState,
)
from src.shared.eventsourcing import EventSourcedRepository, InMemoryEventStore
from src.shared.money import Money, TaxRate
from src.shared.types import ConnectionId, OrderId, TenantId


def _line(product_key: str, qty, line_id: str, kind: str = KIND_PHYSICAL) -> OrderLine:
    return OrderLine(
        product_key=product_key, quantity=qty, unit_of_measure="EA", line_id=line_id, kind=kind
    )


def _lines() -> list[OrderLine]:
    return [_line("ANVIL", 2, "l_anvil")]


def _order() -> Order:
    return Order.submit(
        order_id=OrderId("ord_1"),
        tenant_id=TenantId("tnt_a"),
        client_reference="PO-1",
        lines=_lines(),
        quote_id="qot_1",
        subsidiary_id="oc_1",
        end_customer_name="Acme Downstream",
        ship_to="1 Main St",
        routed_to_connection_id="conn_1",
    )


def test_submit_sets_state_and_derives_product_keys() -> None:
    order = _order()
    assert order.state is OrderState.SUBMITTED
    assert order.product_keys == ["ANVIL"]
    assert order.quote_id == "qot_1"
    assert order.end_customer_name == "Acme Downstream"
    assert order.has_pending


def test_submit_rejects_empty_or_nonpositive_or_idless_lines() -> None:
    with pytest.raises(ValueError):
        Order.submit(order_id=OrderId("o"), tenant_id=TenantId("t"), client_reference="r", lines=[])
    with pytest.raises(ValueError):
        Order.submit(
            order_id=OrderId("o"),
            tenant_id=TenantId("t"),
            client_reference="r",
            lines=[_line("X", 0, "l_x")],
        )
    with pytest.raises(ValueError):
        Order.submit(
            order_id=OrderId("o"),
            tenant_id=TenantId("t"),
            client_reference="r",
            lines=[OrderLine(product_key="X", quantity=1, unit_of_measure="EA", line_id="")],
        )


def test_happy_path_lifecycle() -> None:
    order = _order()
    order.validate()
    order.accept()
    order.send_to_erp("S00001")
    order.confirm()
    order.close()  # CONFIRMED -> CLOSED directly; no FULFILLED lifecycle step anymore
    assert order.state is OrderState.CLOSED
    assert order.owning_connection_id == ConnectionId("conn_1")
    assert order.erp_order_id == "S00001"


def test_invalid_transition_raises() -> None:
    order = _order()
    with pytest.raises(OrderInvalidTransition):
        order.confirm()  # cannot confirm a freshly submitted order


def test_confirm_is_idempotent() -> None:
    order = _order()
    order.validate()
    order.accept()
    order.send_to_erp("S1")
    order.confirm()
    order.collect_events()
    order.confirm()  # repeat -> no-op, no new event
    assert order.collect_events() == []


def test_cannot_cancel_closed_order() -> None:
    order = _order()
    order.validate()
    order.accept()
    order.send_to_erp("S1")
    order.confirm()
    order.close()
    with pytest.raises(OrderInvalidTransition):
        order.cancel("changed mind")


def test_event_sourced_round_trip_via_repository() -> None:
    store = InMemoryEventStore()
    repo: EventSourcedRepository[Order] = EventSourcedRepository(store, Order)
    order = _order()
    order.validate()
    order.accept()
    repo.save(order)

    reloaded = repo.get("ord_1")
    assert reloaded.state is OrderState.ACCEPTED  # formerly READY_FOR_DELIVERY
    assert reloaded.owning_connection_id == ConnectionId("conn_1")
    assert reloaded.client_reference == "PO-1"
    assert reloaded.version == order.version


def test_legacy_ready_for_delivery_snapshot_restores_as_accepted() -> None:
    # A pre-Increment-5 snapshot carried the state value "READY_FOR_DELIVERY" — it must
    # restore as the renamed ACCEPTED, not blow up (Q2=A backward-compat).
    order = Order("ord_legacy")
    order.restore(
        {
            "tenant_id": "tnt_a",
            "client_reference": "PO",
            "lines": [],
            "product_keys": [],
            "state": "READY_FOR_DELIVERY",
            "owning_connection_id": "conn_1",
            "erp_order_id": None,
            "retry_attempt": 0,
        }
    )
    assert order.state is OrderState.ACCEPTED


def test_quantity_is_decimal_and_survives_event_replay_exactly() -> None:
    store = InMemoryEventStore()
    repo: EventSourcedRepository[Order] = EventSourcedRepository(store, Order)
    order = Order.submit(
        order_id=OrderId("ord_2"),
        tenant_id=TenantId("tnt_a"),
        client_reference="PO-2",
        lines=[_line("ANVIL", Decimal("2.1"), "l_a")],
    )
    assert isinstance(order.lines[0].quantity, Decimal)
    repo.save(order)

    reloaded = repo.get("ord_2")
    assert reloaded.lines[0].quantity == Decimal("2.1")
    assert isinstance(reloaded.lines[0].quantity, Decimal)


def test_priced_line_survives_event_replay_exactly() -> None:
    store = InMemoryEventStore()
    repo: EventSourcedRepository[Order] = EventSourcedRepository(store, Order)
    order = Order.submit(
        order_id=OrderId("ord_3"),
        tenant_id=TenantId("tnt_a"),
        client_reference="PO-3",
        lines=[
            OrderLine(
                product_key="ANVIL",
                quantity=Decimal("2.5"),
                unit_of_measure="EA",
                line_id="l_a",
                unit_price=Money(Decimal("19.99"), "USD"),
                line_discount=Money(Decimal("1.50"), "USD"),
                tax_rates=[TaxRate("VAT", Decimal("0.20"), inclusive=False)],
            )
        ],
    )
    repo.save(order)

    line = repo.get("ord_3").lines[0]
    assert line.unit_price == Money(Decimal("19.99"), "USD")
    assert line.line_discount == Money(Decimal("1.50"), "USD")
    assert line.tax_rates == [TaxRate("VAT", Decimal("0.20"), inclusive=False)]


def test_snapshot_round_trip() -> None:
    store = InMemoryEventStore()
    repo: EventSourcedRepository[Order] = EventSourcedRepository(store, Order, snapshot_every=1)
    order = _order()
    repo.save(order)
    assert store.load_snapshot("ord_1") is not None
    assert repo.get("ord_1").state is OrderState.SUBMITTED


def _confirmed_order_with_two_lines(anvil_kind: str = KIND_PHYSICAL) -> Order:
    order = Order.submit(
        order_id=OrderId("ord_pf"),
        tenant_id=TenantId("tnt_a"),
        client_reference="PO-PF",
        lines=[
            _line("ANVIL", Decimal(10), "l_anvil", anvil_kind),
            _line("SPRING", Decimal(5), "l_spring"),
        ],
        routed_to_connection_id="conn_1",
    )
    order.validate()
    order.accept()
    order.send_to_erp("S001")
    order.confirm()
    return order


def test_fulfillment_status_is_orthogonal_to_order_state() -> None:
    order = _confirmed_order_with_two_lines()
    assert order.fulfillment_status is FulfillmentStatus.UNFULFILLED
    assert order.state is OrderState.CONFIRMED

    order.record_fulfillment("l_anvil", Decimal(10))
    assert (
        order.fulfillment_status is FulfillmentStatus.PARTIALLY_FULFILLED
    )  # SPRING not yet shipped
    assert order.state is OrderState.CONFIRMED  # lifecycle untouched

    order.record_fulfillment("l_spring", Decimal(5))
    assert order.fulfillment_status is FulfillmentStatus.FULFILLED


def test_fulfillment_is_additive_across_multiple_shipments() -> None:
    order = _confirmed_order_with_two_lines()
    order.record_fulfillment("l_anvil", Decimal(4))
    order.record_fulfillment("l_anvil", Decimal(6))  # a second, partial shipment
    assert order.shipped_qty_by_line["l_anvil"] == Decimal(10)
    assert order.fulfillment_status is FulfillmentStatus.PARTIALLY_FULFILLED  # SPRING still open


def test_shipped_and_delivered_are_different_facts_for_a_box() -> None:
    # A physical line (box) ships but is NOT delivered until a carrier/POD is recorded (FR-D2/D3).
    order = _confirmed_order_with_two_lines(anvil_kind=KIND_PHYSICAL)
    order.record_fulfillment("l_anvil", Decimal(10))  # shipped, no carrier/POD
    order.record_fulfillment("l_spring", Decimal(5))
    assert order.fulfillment_status is FulfillmentStatus.FULFILLED  # shipped in full
    assert order.delivery_status is DeliveryStatus.NOT_DELIVERED  # but not delivered

    order.record_fulfillment(
        "l_anvil", Decimal(0) + Decimal(10), carrier="DHL"
    )  # now with a carrier
    # SPRING (physical) still has no carrier -> partially delivered overall
    assert order.delivery_status is DeliveryStatus.PARTIALLY_DELIVERED


def test_a_license_is_delivered_on_ship() -> None:
    order = _confirmed_order_with_two_lines(anvil_kind=KIND_LICENSE)
    order.record_fulfillment(
        "l_anvil", Decimal(10)
    )  # license: delivered on ship, no carrier needed
    assert order.delivered_qty_by_line["l_anvil"] == Decimal(10)


def test_invoice_status_tracks_independently_of_fulfillment_status() -> None:
    order = _confirmed_order_with_two_lines()
    order.record_fulfillment("l_anvil", Decimal(10))
    order.record_fulfillment("l_spring", Decimal(5))
    assert order.fulfillment_status is FulfillmentStatus.FULFILLED
    assert order.invoice_status is InvoiceStatus.NOT_INVOICED

    order.record_invoice("l_anvil", Decimal(10))
    assert order.invoice_status is InvoiceStatus.PARTIALLY_INVOICED
    order.record_invoice("l_spring", Decimal(5))
    assert order.invoice_status is InvoiceStatus.INVOICED


def test_cannot_record_fulfillment_before_confirmed() -> None:
    order = _order()  # fresh, still SUBMITTED
    with pytest.raises(OrderInvalidTransition):
        order.record_fulfillment("l_anvil", Decimal(1))


def test_vendor_date_is_scheduled() -> None:
    order = _confirmed_order_with_two_lines()
    order.set_vendor_date("l_anvil", "2026-10-15")
    assert order.vendor_date_by_line["l_anvil"] == "2026-10-15"
    with pytest.raises(ValueError):
        order.set_vendor_date("l_missing", "2026-10-15")


def test_fulfillment_status_survives_event_replay() -> None:
    store = InMemoryEventStore()
    repo: EventSourcedRepository[Order] = EventSourcedRepository(store, Order)
    order = _confirmed_order_with_two_lines()
    order.record_fulfillment("l_anvil", Decimal(10))
    repo.save(order)

    reloaded = repo.get("ord_pf")
    assert reloaded.fulfillment_status is FulfillmentStatus.PARTIALLY_FULFILLED
    assert reloaded.shipped_qty_by_line["l_anvil"] == Decimal(10)


def test_erp_refusal_during_delivery_is_recorded_as_a_rejection() -> None:
    from src.modules.sales.ordering.domain.events import OrderRejected

    order = _order()
    order.validate()
    order.accept()
    order.reject("erp_rejected", "customer on hold")
    events = order.collect_events()
    assert isinstance(events[-1], OrderRejected)
    assert events[-1].reason_code == "erp_rejected"


def test_erp_refusal_after_retries_is_recorded_as_a_rejection() -> None:
    from src.modules.sales.ordering.domain.events import OrderRejected

    order = _order()
    order.validate()
    order.accept()
    order.mark_retrying(attempt=1, next_retry_at="2026-10-26T10:00:00Z")
    order.reject("erp_rejected", "customer on hold")
    assert isinstance(order.collect_events()[-1], OrderRejected)


def test_a_refusal_after_the_erp_took_the_order_is_still_invalid() -> None:
    order = _order()
    order.validate()
    order.accept()
    order.send_to_erp("S1")
    with pytest.raises(OrderInvalidTransition):
        order.reject("erp_rejected", "too late")
