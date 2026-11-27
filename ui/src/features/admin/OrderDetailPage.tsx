import { useState, type FormEvent } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { OrderDetailBody } from "../../components/OrderDetailBody";
import { PageHeader } from "../../components/PageHeader";
import { StatusBadge } from "../../components/StatusBadge";
import { useCancelOrder, useOperatorOrder, useResellers, useSubsidiaries } from "../../hooks/useAdmin";
import { statusLabel } from "../../lib/statusLabel";

/** One order, with ERP identity (owning connection, ERP order id) and the operator actions. */
export function OrderDetailPage() {
  const { orderId = "" } = useParams();
  const navigate = useNavigate();
  const { data: order, isLoading, error } = useOperatorOrder(orderId);
  const { data: subsidiaries } = useSubsidiaries();
  const { data: resellers } = useResellers();
  const cancelOrder = useCancelOrder();
  const [cancelling, setCancelling] = useState(false);
  const [reason, setReason] = useState("");

  async function handleCancel(e: FormEvent) {
    e.preventDefault();
    if (!order) return;
    await cancelOrder.mutateAsync({ orderId: order.orderId, reason: reason.trim() });
    setCancelling(false);
    setReason("");
  }

  if (isLoading) return <p className="muted">Loading…</p>;
  if (error) return <div className="callout callout--danger">Could not load order: {error.message}</div>;
  if (!order) return <p className="muted">Order not found.</p>;

  const subsidiaryName = (subsidiaries ?? []).find((s) => s.subsidiaryId === order.parties.subsidiaryId)?.name;
  const resellerName = (resellers ?? []).find((r) => r.tenantId === order.tenantId)?.name ?? order.tenantId;

  return (
    <>
      <PageHeader
        eyebrow={<Link to="/admin/orders">Orders</Link>}
        title={
          <>
            {order.orderId} <StatusBadge status={statusLabel(order.status)} />
          </>
        }
        subtitle={`Reseller ${resellerName}, reference ${order.clientReference}.`}
        actions={
          <>
            <button className="erp-btn erp-btn--secondary" type="button" onClick={() => navigate(`/orders/${order.orderId}/events`)}>
              Open event stream
            </button>
            <button className="erp-btn erp-btn--ghost" type="button" onClick={() => setCancelling((v) => !v)}>
              {cancelling ? "Keep order" : "Cancel order"}
            </button>
          </>
        }
      />
      {cancelling && (
        <form className="panel stack" onSubmit={handleCancel}>
          <div className="field">
            <label htmlFor="cancelReason">Why is this order being cancelled?</label>
            <input className="input" id="cancelReason" value={reason} onChange={(e) => setReason(e.target.value)} required />
          </div>
          {cancelOrder.error && <div className="callout callout--danger">{(cancelOrder.error as Error).message}</div>}
          <div className="actions">
            <button className="erp-btn erp-btn--primary" type="submit" disabled={cancelOrder.isPending}>
              {cancelOrder.isPending ? "Cancelling…" : "Confirm cancel"}
            </button>
          </div>
        </form>
      )}
      <OrderDetailBody order={order} subsidiaryName={subsidiaryName} />
    </>
  );
}
