import { Link } from "react-router-dom";

import { DataTable, type Column } from "../../components/DataTable";
import { StatusBadge } from "../../components/StatusBadge";
import { useOperatorOrders } from "../../hooks/useAdmin";
import type { OperatorOrder } from "../../api/queries/admin";
import { statusLabel } from "../../lib/statusLabel";

const ATTENTION_STATUSES = new Set(["RETRYING", "REJECTED", "CANCELLED"]);

/** Orders that could not be delivered to an ERP (or were cancelled), across every
 * tenant — the cross-tenant debugging view. Built from the same order data as
 * OrdersPage, filtered, rather than a separate backend concept. */
export function FailedMessagesPage() {
  const { data: orders, isLoading, error } = useOperatorOrders();

  const attention = (orders ?? []).filter((o) => ATTENTION_STATUSES.has(o.status));
  const counts = {
    retrying: attention.filter((o) => o.status === "RETRYING").length,
    rejected: attention.filter((o) => o.status === "REJECTED").length,
    cancelled: attention.filter((o) => o.status === "CANCELLED").length,
  };

  const columns: Column<OperatorOrder>[] = [
    { key: "orderId", header: "Order", render: (o) => <Link to={`/admin/orders/${o.orderId}`}>{o.orderId}</Link> },
    { key: "tenant", header: "Tenant", render: (o) => <span className="id">{o.tenantId}</span> },
    { key: "connection", header: "Connection", render: (o) => o.owningConnectionId ?? "—" },
    { key: "status", header: "Status", render: (o) => <StatusBadge status={statusLabel(o.status)} /> },
  ];

  return (
    <>
      <div className="pagehead">
        <div>
          <h1>Failed messages</h1>
          <p>Orders that could not be delivered to an ERP, or were cancelled. Retrying ones resolve on their own.</p>
        </div>
      </div>
      <div className="statgrid">
        <div className="stat">
          <b style={{ color: "var(--status-warning-fg)" }}>{counts.retrying}</b>
          <span>Retrying</span>
        </div>
        <div className="stat">
          <b style={{ color: "var(--status-danger-fg)" }}>{counts.rejected}</b>
          <span>Rejected by ERP</span>
        </div>
        <div className="stat">
          <b style={{ color: "var(--status-danger-fg)" }}>{counts.cancelled}</b>
          <span>Cancelled</span>
        </div>
      </div>
      {error && <div className="callout callout--danger">Could not load orders: {error.message}</div>}
      <DataTable
        columns={columns}
        rows={attention}
        rowKey={(o) => o.orderId}
        isLoading={isLoading}
        emptyMessage="Nothing needs attention right now"
      />
    </>
  );
}
