import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { Search } from "lucide-react";

import { DataTable, type Column } from "../../components/DataTable";
import { FilterMenu } from "../../components/FilterMenu";
import { PageHeader } from "../../components/PageHeader";
import { StatusBadge } from "../../components/StatusBadge";
import { useNotifications, useOperatorOrders, useSubsidiaries } from "../../hooks/useAdmin";
import type { NotificationDelivery } from "../../api/queries/admin";
import { statusLabel } from "../../lib/statusLabel";

const EVENT_LABEL: Record<string, string> = {
  OrderSentToErp: "Open",
  OrderConfirmed: "Confirmed",
  OrderClosed: "Closed",
  OrderRejected: "Rejected",
  OrderRetrying: "Retrying",
  OrderCancelled: "Cancelled",
  ShipmentRecorded: "Shipment recorded",
  InvoiceRecorded: "Invoice recorded",
};

const DELIVERY_FILTERS = ["all", "DELIVERED", "RETRYING", "FAILED"] as const;
const DELIVERY_OPTIONS = DELIVERY_FILTERS.map((s) => ({ value: s, label: s === "all" ? "All" : statusLabel(s) }));

function formatTime(iso: string): string {
  return new Date(iso).toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

export function NotificationsPage() {
  const navigate = useNavigate();
  const { data, isLoading, error } = useNotifications();
  const { data: orders } = useOperatorOrders();
  const { data: subsidiaries } = useSubsidiaries();
  const [search, setSearch] = useState("");
  const [eventType, setEventType] = useState("all");
  const [delivery, setDelivery] = useState<(typeof DELIVERY_FILTERS)[number]>("all");

  const subsidiaryByOrder = new Map((orders ?? []).map((o) => [o.orderId, o.parties.subsidiaryId]));
  const nameById = new Map((subsidiaries ?? []).map((s) => [s.subsidiaryId, s.name]));

  function subsidiaryName(orderId: string): string {
    const id = subsidiaryByOrder.get(orderId) ?? "";
    if (!id) return "";
    return nameById.get(id) ?? id;
  }

  const eventTypes = Array.from(new Set((data ?? []).map((d) => d.eventType)));

  const rows = [...(data ?? [])]
    .filter((d) => delivery === "all" || d.status === delivery)
    .filter((d) => eventType === "all" || d.eventType === eventType)
    .filter((d) => {
      const haystack = [d.tenantId, d.orderId, EVENT_LABEL[d.eventType] ?? d.eventType, subsidiaryName(d.orderId)].join(" ").toLowerCase();
      return haystack.includes(search.toLowerCase());
    })
    .sort((a, b) => b.occurredAt.localeCompare(a.occurredAt));

  const columns: Column<NotificationDelivery>[] = [
    { key: "when", header: "When", render: (d) => formatTime(d.occurredAt), sortValue: (d) => new Date(d.occurredAt).getTime() },
    { key: "reseller", header: "Reseller", render: (d) => <span className="id">{d.tenantId}</span>, sortValue: (d) => d.tenantId },
    {
      key: "event",
      header: "Notification",
      render: (d) => EVENT_LABEL[d.eventType] ?? d.eventType,
      sortValue: (d) => EVENT_LABEL[d.eventType] ?? d.eventType,
    },
    { key: "status", header: "Delivery", render: (d) => <StatusBadge status={statusLabel(d.status)} />, sortValue: (d) => d.status },
    { key: "subsidiary", header: "Subsidiary", render: (d) => subsidiaryName(d.orderId) || "—", sortValue: (d) => subsidiaryName(d.orderId) },
    { key: "order", header: "Order", render: (d) => <span className="id">{d.orderId}</span>, sortValue: (d) => d.orderId },
  ];

  return (
    <>
      <PageHeader title="Notifications" subtitle="Every status update sent to a reseller, across every reseller. Open a row to see the order." />
      <div className="toolbar">
        <div className="search-input">
          <Search size={15} strokeWidth={2} className="search-input__icon" />
          <input
            className="input"
            type="search"
            placeholder="Search by reseller, order, or event"
            style={{ width: 280 }}
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>
        <FilterMenu
          groups={[
            { label: "Delivery", options: DELIVERY_OPTIONS, value: delivery, onChange: (v) => setDelivery(v as (typeof DELIVERY_FILTERS)[number]) },
            {
              label: "Event type",
              options: [{ value: "all", label: "All events" }, ...eventTypes.map((t) => ({ value: t, label: EVENT_LABEL[t] ?? t }))],
              value: eventType,
              onChange: setEventType,
            },
          ]}
        />
      </div>
      {error && <div className="callout callout--danger">Could not load notifications: {error.message}</div>}
      <DataTable
        columns={columns}
        rows={rows}
        rowKey={(d) => d.deliveryId}
        isLoading={isLoading}
        emptyMessage="No notifications match this filter"
        onRowClick={(d) => navigate(`/admin/orders/${d.orderId}`)}
        pageSize={10}
      />
    </>
  );
}
