import { Link, useNavigate, useParams } from "react-router-dom";

import { OrderDetailBody } from "../../components/OrderDetailBody";
import { PageHeader } from "../../components/PageHeader";
import { StatusBadge } from "../../components/StatusBadge";
import { useOperatorOrder, useResellers, useSubsidiaries } from "../../hooks/useAdmin";
import { statusLabel } from "../../lib/statusLabel";

/** Operator view of one order: everything the reseller sees, plus ERP identity (owning
 * connection, ERP order id) — never shown on the reseller-facing OrderDetailPage. */
export function OrderDetailPage() {
  const { orderId = "" } = useParams();
  const navigate = useNavigate();
  const { data: order, isLoading, error } = useOperatorOrder(orderId);
  const { data: subsidiaries } = useSubsidiaries();
  const { data: resellers } = useResellers();

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
          <button className="erp-btn erp-btn--secondary" type="button" onClick={() => navigate(`/orders/${order.orderId}/events`)}>
            Open event stream
          </button>
        }
      />
      <OrderDetailBody order={order} subsidiaryName={subsidiaryName} />
    </>
  );
}
