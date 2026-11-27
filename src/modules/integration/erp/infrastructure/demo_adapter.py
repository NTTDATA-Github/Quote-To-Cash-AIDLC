"""Demo-only ERP adapter: rejects orders for chosen customers, so conflicts show in the demo.

Wraps the stub adapter and changes one thing: an order whose ERP customer id is on the list is
rejected as terminal, the same way a real ERP refuses an order (customer on hold). Every other
call passes straight through. Enabled only when DEMO_REJECT_ERP_CUSTOMERS is set.
"""

from __future__ import annotations

from typing import Any

from ..application.ports import ErpAdapter, ErpTarget, SubmissionResult

DEMO_REJECTION = "Customer on hold in the ERP (demo rule)"

# What the demo ERP says for each demo customer. One message per cause, so the conflict page
# shows every category. Customer 7 gets a message no rule knows, so it lands in "Other".
DEMO_REJECTIONS: dict[str, str] = {
    "1": DEMO_REJECTION,
    "3": "Unknown product SKU ANVIL-9",
    "4": "Unit price differs from the price list",
    "5": "Ship-to address is incomplete",
    "6": "Order already exists in the ERP",
    "7": "Unexpected response code 0x4F2 from the ERP",
}


class DemoRejectingAdapter:
    def __init__(self, inner: ErpAdapter, reject_customers: frozenset[str]) -> None:
        self._inner = inner
        self._reject_customers = reject_customers
        self.capabilities = inner.capabilities

    def submit(self, target: ErpTarget, order_payload: dict[str, Any]) -> SubmissionResult:
        if str(order_payload.get("erp_customer_id")) in self._reject_customers:
            message = DEMO_REJECTIONS.get(str(order_payload.get("erp_customer_id")), DEMO_REJECTION)
            return SubmissionResult(success=False, error=message, terminal=True)
        return self._inner.submit(target, order_payload)

    def fetch_status(self, target: ErpTarget, erp_order_id: str) -> dict[str, str] | None:
        return self._inner.fetch_status(target, erp_order_id)

    def fetch_partner_orders(self, target: ErpTarget, partner_id: str) -> Any:
        return self._inner.fetch_partner_orders(target, partner_id)

    def fetch_shipments(self, target: ErpTarget, erp_order_id: str) -> Any:
        return self._inner.fetch_shipments(target, erp_order_id)

    def fetch_invoices(self, target: ErpTarget, erp_order_id: str) -> Any:
        return self._inner.fetch_invoices(target, erp_order_id)

    def cancel(self, target: ErpTarget, erp_order_id: str) -> SubmissionResult:
        return self._inner.cancel(target, erp_order_id)
