import { useState } from "react";
import { Link, useParams } from "react-router-dom";

import { PageHeader } from "../../components/PageHeader";
import { useOperatorOrder, useResellers } from "../../hooks/useAdmin";
import { useOrderEvents } from "../../hooks/useEvents";
import type { OrderEvent } from "../../api/queries/events";

function formatTime(iso: string): string {
  return new Date(iso).toLocaleString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

/** The developer/operator view of an order's raw event stream — exactly what's in the
 * event store, in order. This is the "delivery log" for debugging ERP delivery: it shows
 * every OrderSentToErp / OrderConfirmed / etc. event as it actually happened, not a
 * reseller-facing summary. See docs/event-sourcing-explained.md. */
export function OrderEventsPage() {
  const { orderId = "" } = useParams();
  const { data: order } = useOperatorOrder(orderId);
  const { data: resellers } = useResellers();
  const { data: events, isLoading, error } = useOrderEvents(orderId);
  const [selected, setSelected] = useState<OrderEvent | null>(null);
  const resellerName = order ? (resellers ?? []).find((r) => r.tenantId === order.tenantId)?.name ?? order.tenantId : "";

  const active = selected ?? (events && events.length > 0 ? events[events.length - 1] : null);

  return (
    <>
      <PageHeader
        eyebrow={
          <>
            <Link to="/admin/orders">Orders</Link> / <Link to={`/admin/orders/${orderId}`}>{orderId}</Link>
          </>
        }
        title="Event stream"
        subtitle={
          <>
            Every event recorded for this order, in the order it happened.
            {order && <> Reseller {resellerName}, currently {order.status}.</>}
          </>
        }
      />
      {error && <div className="callout callout--danger">Could not load events: {error.message}</div>}
      <div className="split">
        <div className="erp-table-wrap">
          <table className="erp-table">
            <thead>
              <tr>
                <th>Time</th>
                <th>Event</th>
                <th className="num">Version</th>
                <th>Correlation</th>
              </tr>
            </thead>
            <tbody>
              {isLoading && (
                <tr>
                  <td colSpan={4} className="muted">
                    Loading…
                  </td>
                </tr>
              )}
              {(events ?? []).map((e) => (
                <tr key={e.version} aria-selected={active === e} onClick={() => setSelected(e)} style={{ cursor: "pointer" }}>
                  <td className="id">{formatTime(e.occurredAt)}</td>
                  <td className="id">{e.eventType}</td>
                  <td className="num">{e.version}</td>
                  <td className="mono">{e.correlationId ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <section className="panel" aria-label="Event detail">
          <div className="panel-head">
            <h2>{active ? active.eventType : "Event detail"}</h2>
          </div>
          {active ? (
            <>
              <dl className="kv">
                <dt>Version</dt>
                <dd className="mono">{active.version}</dd>
                <dt>Occurred at</dt>
                <dd className="mono">{formatTime(active.occurredAt)}</dd>
                <dt>Correlation ID</dt>
                <dd className="mono">{active.correlationId ?? "—"}</dd>
              </dl>
              <div className="heading" style={{ font: "600 14px/20px var(--font-sans)" }}>
                Payload
              </div>
              <pre className="code">{JSON.stringify(active.payload, null, 2)}</pre>
            </>
          ) : (
            <p className="muted">Select an event to see its payload.</p>
          )}
        </section>
      </div>
    </>
  );
}
