import { useState } from "react";
import { Link } from "react-router-dom";
import { Search } from "lucide-react";

import { DataTable, type Column } from "../../components/DataTable";
import { FilterMenu } from "../../components/FilterMenu";
import { PageHeader } from "../../components/PageHeader";
import { StatusBadge } from "../../components/StatusBadge";
import { useConnections, useOperatorOrders, useResellers } from "../../hooks/useAdmin";
import type { OperatorOrder } from "../../api/queries/admin";
import { statusLabel } from "../../lib/statusLabel";
import { statusRank } from "../../lib/orderStage";

const ATTENTION_STATUSES = new Set(["RETRYING", "REJECTED", "CANCELLED"]);
type AttentionStatus = "all" | "RETRYING" | "REJECTED" | "CANCELLED";
const STATUS_OPTIONS: { value: AttentionStatus; label: string }[] = [
  { value: "all", label: "All" },
  { value: "RETRYING", label: "Retrying" },
  { value: "REJECTED", label: "Rejected by ERP" },
  { value: "CANCELLED", label: "Cancelled" },
];

/** Orders that could not be delivered to an ERP (or were cancelled), across every
 * tenant — the cross-tenant debugging view. Built from the same order data as
 * OrdersPage, filtered, rather than a separate backend concept. */
export function FailedMessagesPage() {
  const { data: orders, isLoading, error } = useOperatorOrders();
  const { data: resellers } = useResellers();
  const { data: connections } = useConnections();
  const [status, setStatus] = useState<AttentionStatus>("all");
  const [search, setSearch] = useState("");

  const resellerNameById = new Map((resellers ?? []).map((r) => [r.tenantId, r.name]));
  const connectionLabelById = new Map((connections ?? []).map((c) => [c.connectionId, c.instanceLabel]));
  const resellerName = (o: OperatorOrder) => resellerNameById.get(o.tenantId) ?? o.tenantId;
  const connectionLabel = (o: OperatorOrder) =>
    o.owningConnectionId ? connectionLabelById.get(o.owningConnectionId) ?? o.owningConnectionId : "—";

  const attention = (orders ?? []).filter((o) => ATTENTION_STATUSES.has(o.status));
  const counts = {
    RETRYING: attention.filter((o) => o.status === "RETRYING").length,
    REJECTED: attention.filter((o) => o.status === "REJECTED").length,
    CANCELLED: attention.filter((o) => o.status === "CANCELLED").length,
  };

  const rows = attention
    .filter((o) => status === "all" || o.status === status)
    .filter((o) =>
      [o.orderId, o.tenantId, resellerName(o), o.owningConnectionId ?? ""].join(" ").toLowerCase().includes(search.toLowerCase()),
    );

  const columns: Column<OperatorOrder>[] = [
    { key: "orderId", header: "Order", render: (o) => <Link to={`/admin/orders/${o.orderId}`}>{o.orderId}</Link>, sortValue: (o) => o.orderId },
    { key: "tenant", header: "Reseller", render: (o) => resellerName(o), sortValue: (o) => resellerName(o) },
    { key: "connection", header: "Connection", render: (o) => connectionLabel(o), sortValue: (o) => connectionLabel(o) },
    { key: "status", header: "Status", render: (o) => <StatusBadge status={statusLabel(o.status)} />, sortValue: (o) => statusRank(o.status) },
  ];

  return (
    <>
      <PageHeader title="Failed messages" subtitle="Orders that could not be delivered to an ERP, or were cancelled. Retrying ones resolve on their own." />
      <div className="statgrid">
        <div className="stat">
          <b style={{ color: "var(--status-warning-fg)" }}>{counts.RETRYING}</b>
          <span>Retrying</span>
        </div>
        <div className="stat">
          <b style={{ color: "var(--status-danger-fg)" }}>{counts.REJECTED}</b>
          <span>Rejected by ERP</span>
        </div>
        <div className="stat">
          <b style={{ color: "var(--status-danger-fg)" }}>{counts.CANCELLED}</b>
          <span>Cancelled</span>
        </div>
      </div>
      <div className="toolbar">
        <div className="search-input">
          <Search size={15} strokeWidth={2} className="search-input__icon" />
          <input
            className="input"
            type="search"
            placeholder="Search by order, reseller, or connection"
            style={{ width: 300 }}
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>
        <FilterMenu groups={[{ label: "Status", options: STATUS_OPTIONS, value: status, onChange: (v) => setStatus(v as AttentionStatus) }]} />
      </div>
      {error && <div className="callout callout--danger">Could not load orders: {error.message}</div>}
      <DataTable
        columns={columns}
        rows={rows}
        rowKey={(o) => o.orderId}
        isLoading={isLoading}
        emptyMessage="Nothing needs attention right now"
        pageSize={10}
      />
    </>
  );
}
