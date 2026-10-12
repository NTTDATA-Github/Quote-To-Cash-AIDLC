import { Link, useNavigate, useParams } from "react-router-dom";

import { OrderTimeline } from "../../components/OrderTimeline";
import { StatusBadge } from "../../components/StatusBadge";
import { useAuth } from "../../auth/AuthContext";
import { useCancelOrder, useOrder } from "../../hooks/useOrders";
import { formatMoney } from "../../lib/money";
import { statusLabel } from "../../lib/statusLabel";

const CANCELLABLE = new Set(["SUBMITTED", "VALIDATED"]);

export function OrderDetailPage() {
  const { orderId = "" } = useParams();
  const navigate = useNavigate();
  const { roles } = useAuth();
  const { data: order, isLoading, error } = useOrder(orderId);
  const cancelOrder = useCancelOrder();

  if (isLoading) return <p className="muted">Loading…</p>;
  if (error) return <div className="callout callout--danger">Could not load order: {error.message}</div>;
  if (!order) return <p className="muted">Order not found.</p>;

  const canCancel = CANCELLABLE.has(order.status);

  function handleCancel() {
    const reason = window.prompt("Reason for cancelling this order?");
    if (!reason) return;
    cancelOrder.mutate({ orderId, reason });
  }

  return (
    <>
      <div className="pagehead">
        <div>
          <h1>
            Order {order.orderId} <StatusBadge status={statusLabel(order.status)} />
          </h1>
          <p>Your reference {order.clientReference}.</p>
        </div>
        <div className="actions">
          <button className="erp-btn erp-btn--danger" type="button" disabled={!canCancel || cancelOrder.isPending} onClick={handleCancel}>
            Cancel order
          </button>
        </div>
      </div>
      <div className="split">
        <div className="stack">
          <section className="panel">
            <h2>Order lines</h2>
            <div className="erp-table-wrap">
              <table className="erp-table">
                <thead>
                  <tr>
                    <th>Item</th>
                    <th>Kind</th>
                    <th className="num">Qty</th>
                    <th>Unit</th>
                    <th className="num">Unit price</th>
                    <th className="num">Line total</th>
                    <th className="num">Shipped</th>
                    <th className="num">Delivered</th>
                  </tr>
                </thead>
                <tbody>
                  {order.lines.map((line) => (
                    <tr key={line.lineId}>
                      <td className="id">{line.productKey}</td>
                      <td>{line.kind === "LICENSE" ? "License" : "Box"}</td>
                      <td className="num">{line.quantity}</td>
                      <td>{line.unitOfMeasure}</td>
                      <td className="num">{formatMoney(line.unitPrice)}</td>
                      <td className="num">{formatMoney(line.lineTotal)}</td>
                      <td className="num">{line.shippedQuantity}</td>
                      <td className="num">{line.deliveredQuantity}</td>
                    </tr>
                  ))}
                </tbody>
                {order.subtotal && (
                  <tfoot>
                    <tr>
                      <td colSpan={5}>Subtotal</td>
                      <td className="num">{formatMoney(order.subtotal)}</td>
                      <td colSpan={2}></td>
                    </tr>
                  </tfoot>
                )}
              </table>
            </div>
          </section>
        </div>
        <div className="stack">
          <section className="panel">
            <h2>Status</h2>
            <dl className="kv">
              <dt>Fulfillment</dt>
              <dd><StatusBadge status={statusLabel(order.fulfillmentStatus)} /></dd>
              <dt>Delivery</dt>
              <dd><StatusBadge status={statusLabel(order.deliveryStatus)} /></dd>
              <dt>Invoice</dt>
              <dd><StatusBadge status={statusLabel(order.invoiceStatus)} /></dd>
            </dl>
          </section>
          <section className="panel">
            <h2>Parties</h2>
            <dl className="kv">
              <dt>End customer</dt>
              <dd>{order.parties.endCustomerName || "—"}</dd>
              <dt>Ship to</dt>
              <dd>{order.parties.shipTo || "—"}</dd>
            </dl>
          </section>
          <section className="panel">
            <h2>Timeline</h2>
            <OrderTimeline timeline={order.timeline} currentStatus={order.status} />
          </section>
          {roles.includes("OPERATOR") && (
            <section className="panel">
              <div className="panel-head">
                <h2>Event stream</h2>
              </div>
              <p className="hint">The raw event history behind this order — useful for debugging delivery to the ERP.</p>
              <button className="erp-btn erp-btn--secondary" type="button" onClick={() => navigate(`/orders/${order.orderId}/events`)}>
                Open event stream
              </button>
            </section>
          )}
        </div>
      </div>
      <p>
        <Link to="/notifications">Back to notifications</Link>
      </p>
    </>
  );
}
