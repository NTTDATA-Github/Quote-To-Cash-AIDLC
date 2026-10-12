import { useNavigate } from "react-router-dom";

import { DataTable, type Column } from "../../components/DataTable";
import { useNotifications } from "../../hooks/useAdmin";
import type { NotificationDelivery } from "../../api/queries/admin";

const EVENT_LABEL: Record<string, string> = {
  OrderSentToErp: "Sent to ERP",
  OrderConfirmed: "Confirmed",
  OrderClosed: "Closed",
  OrderRejected: "Rejected",
  OrderRetrying: "Retrying",
  OrderCancelled: "Cancelled",
  ShipmentRecorded: "Shipment recorded",
  InvoiceRecorded: "Invoice recorded",
};

function formatTime(iso: string): string {
  return new Date(iso).toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

export function NotificationsPage() {
  const navigate = useNavigate();
  const { data, isLoading, error } = useNotifications();
  const rows = [...(data ?? [])].sort((a, b) => b.occurredAt.localeCompare(a.occurredAt));

  const columns: Column<NotificationDelivery>[] = [
    { key: "when", header: "When", render: (d) => formatTime(d.occurredAt) },
    { key: "reseller", header: "Reseller", render: (d) => <span className="id">{d.tenantId}</span> },
    { key: "event", header: "Notification", render: (d) => EVENT_LABEL[d.eventType] ?? d.eventType },
    { key: "status", header: "Delivery", render: (d) => d.status },
    { key: "order", header: "Order", render: (d) => <span className="id">{d.orderId}</span> },
  ];

  return (
    <>
      <div className="pagehead">
        <div>
          <h1>Notifications</h1>
          <p>Every status update sent to a reseller, across every reseller. Open a row to see the order.</p>
        </div>
      </div>
      {error && <div className="callout callout--danger">Could not load notifications: {error.message}</div>}
      <DataTable
        columns={columns}
        rows={rows}
        rowKey={(d) => d.deliveryId}
        isLoading={isLoading}
        emptyMessage="No notifications sent yet"
        onRowClick={(d) => navigate(`/admin/orders/${d.orderId}`)}
      />
    </>
  );
}
