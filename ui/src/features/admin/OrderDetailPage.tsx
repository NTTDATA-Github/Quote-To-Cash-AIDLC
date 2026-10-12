import { Link, useNavigate, useParams } from "react-router-dom";

import { InfoTag } from "../../components/InfoTag";
import { OrderTimeline } from "../../components/OrderTimeline";
import { StatusBadge } from "../../components/StatusBadge";
import { useOperatorOrder } from "../../hooks/useAdmin";
import { formatMoney } from "../../lib/money";
import { statusLabel } from "../../lib/statusLabel";

/** Operator view of one order: everything the reseller sees, plus ERP identity (owning
 * connection, ERP order id) — never shown on the reseller-facing OrderDetailPage. */
export function OrderDetailPage() {
  const { orderId = "" } = useParams();
  const navigate = useNavigate();
  const { data: order, isLoading, error } = useOperatorOrder(orderId);

  if (isLoading) return <p className="muted">Loading…</p>;
  if (error) return <div className="callout callout--danger">Could not load order: {error.message}</div>;
  if (!order) return <p className="muted">Order not found.</p>;

  return (
    <>
      <div className="pagehead">
        <div>
          <h1>
            Order {order.orderId} <StatusBadge status={statusLabel(order.status)} />
          </h1>
          <p>
            Tenant {order.tenantId}, reference {order.clientReference}.
          </p>
        </div>
        <div className="actions">
          <button className="erp-btn erp-btn--secondary" type="button" onClick={() => navigate(`/orders/${order.orderId}/events`)}>
            Open event stream
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
                    <th className="num">Unit price</th>
                    <th className="num">Line total</th>
                    <th className="num">Shipped</th>
                    <th className="num">Delivered</th>
                    <th className="num">Invoiced</th>
                  </tr>
                </thead>
                <tbody>
                  {order.lines.map((line) => (
                    <tr key={line.lineId}>
                      <td className="id">{line.productKey}</td>
                      <td>{line.kind === "LICENSE" ? "License" : "Box"}</td>
                      <td className="num">{line.quantity}</td>
                      <td className="num">{formatMoney(line.unitPrice)}</td>
                      <td className="num">{formatMoney(line.lineTotal)}</td>
                      <td className="num">{line.shippedQuantity}</td>
                      <td className="num">{line.deliveredQuantity}</td>
                      <td className="num">{line.invoicedQuantity}</td>
                    </tr>
                  ))}
                </tbody>
                {order.subtotal && (
                  <tfoot>
                    <tr>
                      <td colSpan={4}>Subtotal</td>
                      <td className="num">{formatMoney(order.subtotal)}</td>
                      <td colSpan={3}></td>
                    </tr>
                  </tfoot>
                )}
              </table>
            </div>
          </section>

          <section className="panel">
            <h2>ERP identity</h2>
            <dl className="kv">
              <dt>
                Owning connection <InfoTag text="Which ERP connection owns the items on this order and receives it." />
              </dt>
              <dd>{order.owningConnectionId ?? "Not yet routed"}</dd>
              <dt>
                ERP order ID <InfoTag text="The order's identifier inside the ERP itself, once it has been sent. The order is placed in the ERP as the reseller's bound customer, keyed on this platform order id for idempotency." />
              </dt>
              <dd className="mono">{order.erpOrderId ?? "—"}</dd>
            </dl>
          </section>
        </div>
        <div className="stack">
          <section className="panel">
            <h2>Fulfillment</h2>
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
              <dt>Subsidiary</dt>
              <dd className="mono">{order.parties.subsidiaryId || "—"}</dd>
            </dl>
          </section>
          <section className="panel">
            <h2>Timeline</h2>
            <OrderTimeline timeline={order.timeline} currentStatus={order.status} />
          </section>
        </div>
      </div>
      <p>
        <Link to="/admin/orders">Back to orders</Link>
      </p>
    </>
  );
}
