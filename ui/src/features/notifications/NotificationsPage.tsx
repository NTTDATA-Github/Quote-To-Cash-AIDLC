import { useNavigate } from "react-router-dom";

import { DataTable, type Column } from "../../components/DataTable";
import { useDeliveryLog } from "../../hooks/useWebhooks";
import type { WebhookDelivery } from "../../api/queries/webhooks";

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

function formatTime(iso: string): string {
  return new Date(iso).toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

export function NotificationsPage() {
  const navigate = useNavigate();
  const { data, isLoading, error } = useDeliveryLog();
  const sent = (data ?? []).filter((d) => d.status === "DELIVERED").sort((a, b) => b.occurredAt.localeCompare(a.occurredAt));

  const columns: Column<WebhookDelivery>[] = [
    { key: "when", header: "When", render: (d) => formatTime(d.occurredAt) },
    { key: "event", header: "Notification", render: (d) => EVENT_LABEL[d.eventType] ?? d.eventType },
    { key: "order", header: "Order", render: (d) => <span className="id">{d.orderId}</span> },
  ];

  return (
    <>
      <div className="pagehead">
        <div>
          <h1>Notifications</h1>
          <p>Status updates that were delivered to you. Open a row to see the order.</p>
        </div>
      </div>
      {error && <div className="callout callout--danger">Could not load notifications: {error.message}</div>}
      <DataTable
        columns={columns}
        rows={sent}
        rowKey={(d) => d.deliveryId}
        isLoading={isLoading}
        emptyMessage="No notifications sent yet"
        onRowClick={(d) => navigate(`/orders/${d.orderId}`)}
      />
    </>
  );
}
