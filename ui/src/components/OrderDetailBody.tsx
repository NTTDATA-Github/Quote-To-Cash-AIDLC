import { InfoTag } from "./InfoTag";
import { OrderTimeline } from "./OrderTimeline";
import { StatusBadge } from "./StatusBadge";
import type { OperatorOrder } from "../api/queries/admin";
import { formatMoney } from "../lib/money";
import { statusLabel } from "../lib/statusLabel";

/** The content of one order's detail view — order lines, ERP identity, fulfillment,
 * parties, timeline. Shared by the full OrderDetailPage and the Kanban board's drawer so
 * the two never drift into showing different things for the same order. */
export function OrderDetailBody({ order, subsidiaryName }: { order: OperatorOrder; subsidiaryName?: string }) {
  return (
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
              Owning connection <InfoTag text="Which ERP connection the order was adopted from." />
            </dt>
            <dd>{order.owningConnectionId ?? "—"}</dd>
            <dt>
              ERP order ID{" "}
              <InfoTag text="The order's identifier inside the ERP itself, set from the document that was adopted — the connection and this id come from the same poll." />
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
            <dd>
              <StatusBadge status={statusLabel(order.fulfillmentStatus)} />
            </dd>
            <dt>Delivery</dt>
            <dd>
              <StatusBadge status={statusLabel(order.deliveryStatus)} />
            </dd>
            <dt>Invoice</dt>
            <dd>
              <StatusBadge status={statusLabel(order.invoiceStatus)} />
            </dd>
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
            <dd>
              {subsidiaryName || order.parties.subsidiaryId || "—"}
              {subsidiaryName && order.parties.subsidiaryId && (
                <>
                  {" "}
                  <span className="mono muted">({order.parties.subsidiaryId})</span>
                </>
              )}
            </dd>
          </dl>
        </section>
        <section className="panel">
          <h2>Timeline</h2>
          <OrderTimeline timeline={order.timeline} currentStatus={order.status} />
        </section>
      </div>
    </div>
  );
}
