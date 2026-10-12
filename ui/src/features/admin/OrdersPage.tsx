import { useState } from "react";
import { Link } from "react-router-dom";

import { DataTable, type Column } from "../../components/DataTable";
import { StatusBadge } from "../../components/StatusBadge";
import { useOperatorOrders } from "../../hooks/useAdmin";
import type { OperatorOrder } from "../../api/queries/admin";
import { statusLabel } from "../../lib/statusLabel";

/** Every order, across every tenant — the cross-tenant visibility an operator needs to
 * debug a specific reseller's order without knowing its id ahead of time. */
export function OrdersPage() {
  const { data: orders, isLoading, error } = useOperatorOrders();
  const [search, setSearch] = useState("");

  const filtered = (orders ?? []).filter(
    (o) =>
      o.orderId.toLowerCase().includes(search.toLowerCase()) ||
      o.tenantId.toLowerCase().includes(search.toLowerCase()) ||
      o.clientReference.toLowerCase().includes(search.toLowerCase()),
  );

  const columns: Column<OperatorOrder>[] = [
    { key: "orderId", header: "Order", render: (o) => <Link to={`/admin/orders/${o.orderId}`}>{o.orderId}</Link> },
    { key: "tenant", header: "Tenant", render: (o) => <span className="id">{o.tenantId}</span> },
    { key: "ref", header: "Reference", render: (o) => o.clientReference },
    { key: "connection", header: "Connection", render: (o) => o.owningConnectionId ?? "—" },
    { key: "erpOrderId", header: "ERP order", render: (o) => (o.erpOrderId ? <span className="mono">{o.erpOrderId}</span> : "—") },
    { key: "status", header: "Status", render: (o) => <StatusBadge status={statusLabel(o.status)} /> },
  ];

  return (
    <>
      <div className="pagehead">
        <div>
          <h1>Orders</h1>
          <p>Every order across every reseller — for debugging, not the reseller's own view.</p>
        </div>
      </div>
      <div className="toolbar">
        <label className="sr" htmlFor="q">
          Search orders
        </label>
        <input
          className="input"
          id="q"
          type="search"
          placeholder="Search by order, tenant, or reference"
          style={{ width: 320 }}
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
      </div>
      {error && <div className="callout callout--danger">Could not load orders: {error.message}</div>}
      <DataTable columns={columns} rows={filtered} rowKey={(o) => o.orderId} isLoading={isLoading} emptyMessage="No orders yet" />
    </>
  );
}
