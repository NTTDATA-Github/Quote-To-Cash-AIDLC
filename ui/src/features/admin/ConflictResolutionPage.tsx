import { useState } from "react";
import { Link } from "react-router-dom";
import { Search } from "lucide-react";

import { DataTable, type Column } from "../../components/DataTable";
import { FilterMenu } from "../../components/FilterMenu";
import { PageHeader } from "../../components/PageHeader";
import { StatusBadge, type Role } from "../../components/StatusBadge";
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

type StaticRow = Record<string, string>;

const CHIP_ROLE: Record<string, Role> = {
  High: "danger",
  Medium: "warning",
  Low: "neutral",
  Open: "progress",
  "In review": "progress",
  Retrying: "warning",
  Healthy: "success",
  Degraded: "warning",
};

function Chip({ value }: { value: string }) {
  return <span className={`erp-badge erp-badge--${CHIP_ROLE[value] ?? "neutral"}`}>{value}</span>;
}

function staticColumns(headers: string[], chipFields: string[] = []): Column<StaticRow>[] {
  return headers.map((header) => ({
    key: header,
    header,
    render: chipFields.includes(header) ? (row) => <Chip value={row[header]} /> : (row) => row[header],
  }));
}

function staticRowKey(row: StaticRow): string {
  return Object.values(row).join("|");
}

const CONFLICT_ROWS: StaticRow[] = [
  { "Order ID": "ord_conn_0847d6c7163a_S00005", "Conflicting Fields": "Quantity (reseller 5, ERP 4)", Severity: "High", Status: "Open", "SLA Remaining": "2h 15m", "Assigned To": "Unassigned", Actions: "Resolve" },
  { "Order ID": "ord_conn_0847d6c7163a_S00004", "Conflicting Fields": "Delivery date, ship-to address", Severity: "Medium", Status: "In review", "SLA Remaining": "6h 40m", "Assigned To": "operator1", Actions: "Resolve" },
  { "Order ID": "ord_conn_0847d6c7163a_S00002", "Conflicting Fields": "Unit price", Severity: "Low", Status: "Open", "SLA Remaining": "1d 3h", "Assigned To": "Unassigned", Actions: "Resolve" },
];

const FAILED_EVENT_ROWS: StaticRow[] = [
  { Priority: "High", "Event Type": "OrderSentToErp", "Conflict Reason": "ERP rejected: customer on hold", Retries: "3", Age: "12m", Status: "Retrying", Actions: "Retry / Dismiss" },
  { Priority: "Medium", "Event Type": "OrderCancelled", "Conflict Reason": "Cancelled in ERP after send", Retries: "0", Age: "1h", Status: "Open", Actions: "Review" },
  { Priority: "Low", "Event Type": "ShipmentRecorded", "Conflict Reason": "Shipped qty exceeds ordered qty", Retries: "1", Age: "3h", Status: "Open", Actions: "Review" },
];

const ERP_SYNC_ROWS: StaticRow[] = [
  { "ERP Name": "Odoo", Status: "Healthy", "Last Sync": "2 min ago", "Pending Write-Backs": "0", "Failed Write-Backs": "0", "Sync Lag": "< 1 min" },
  { "ERP Name": "NetSuite", Status: "Degraded", "Last Sync": "18 min ago", "Pending Write-Backs": "4", "Failed Write-Backs": "2", "Sync Lag": "15 min" },
];

/** Orders that could not be delivered to an ERP (or were cancelled), across every
 * tenant — the cross-tenant debugging view. Built from the same order data as
 * OrdersPage, filtered, rather than a separate backend concept. */
export function ConflictResolutionPage() {
  const { data: orders, isLoading, error } = useOperatorOrders();
  const { data: resellers } = useResellers();
  const { data: connections } = useConnections();
  const [status, setStatus] = useState<AttentionStatus>("all");
  const [search, setSearch] = useState("");
  const [conflictStatus, setConflictStatus] = useState("all");
  const [eventPriority, setEventPriority] = useState("all");
  const [eventStatus, setEventStatus] = useState("all");

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
      <PageHeader title="Conflict resolution" subtitle="Orders where the reseller and the ERP disagree, or that could not be delivered. Review each conflict and decide which side wins." />
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

      <div className="toolbar">
        <h3 style={{ margin: 0, font: "600 16px/32px var(--font-sans)" }}>Conflict Queue</h3>
        <FilterMenu
          groups={[
            {
              label: "Status",
              options: [{ value: "all", label: "All" }],
              value: conflictStatus,
              onChange: setConflictStatus,
            },
          ]}
        />
      </div>
      <DataTable
        columns={staticColumns(["Order ID", "Conflicting Fields", "Severity", "Status", "SLA Remaining", "Assigned To", "Actions"], ["Severity", "Status"])}
        rows={CONFLICT_ROWS}
        rowKey={staticRowKey}
        emptyMessage="No conflicts"
      />

      <div className="toolbar">
        <h3 style={{ margin: 0, font: "600 16px/32px var(--font-sans)" }}>Failed Events</h3>
        <FilterMenu
          groups={[
            { label: "Priority", options: [{ value: "all", label: "All" }], value: eventPriority, onChange: setEventPriority },
            { label: "Status", options: [{ value: "all", label: "All" }], value: eventStatus, onChange: setEventStatus },
          ]}
        />
      </div>
      <DataTable
        columns={staticColumns(["Priority", "Event Type", "Conflict Reason", "Retries", "Age", "Status", "Actions"], ["Priority", "Status"])}
        rows={FAILED_EVENT_ROWS}
        rowKey={staticRowKey}
        emptyMessage="No conflicting events"
      />

      <h3>ERP Sync Status</h3>
      <DataTable
        columns={staticColumns(["ERP Name", "Status", "Last Sync", "Pending Write-Backs", "Failed Write-Backs", "Sync Lag"], ["Status"])}
        rows={ERP_SYNC_ROWS}
        rowKey={staticRowKey}
        emptyMessage="No ERP connections"
      />
    </>
  );
}
