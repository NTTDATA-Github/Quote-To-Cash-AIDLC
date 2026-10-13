import { Building2, Users } from "lucide-react";

import type { OperatorOrder } from "../api/queries/admin";
import { formatMoney } from "../lib/money";
import { timeAgo } from "../lib/timeAgo";

interface KanbanColumnDef {
  key: string;
  label: string;
  statuses: string[];
}

// src/modules/sales/ordering/domain/models.py OrderState. Orders arrive already adopted
// from the ERP (OrderObserved -> SENT_TO_ERP), so the old push-flow states (Submitted,
// Validated, Accepted) never show up live and aren't columns here. Exception states
// (Rejected/Retrying/Cancelled) aren't shown either — they already have a dedicated view
// on Failed messages.
const COLUMNS: KanbanColumnDef[] = [
  { key: "open", label: "Open", statuses: ["SENT_TO_ERP"] },
  { key: "confirmed", label: "Confirmed", statuses: ["CONFIRMED"] },
  { key: "closed", label: "Closed", statuses: ["CLOSED"] },
];

function lastEventAt(o: OperatorOrder): number {
  return o.timeline.reduce((latest, t) => Math.max(latest, new Date(t.occurredAt).getTime()), 0);
}

function columnOf(status: string): KanbanColumnDef | undefined {
  return COLUMNS.find((c) => c.statuses.includes(status));
}

function sumByCurrency(orders: OperatorOrder[]): { currency: string; total: number }[] {
  const totals = new Map<string, number>();
  for (const o of orders) {
    if (!o.subtotal) continue;
    totals.set(o.subtotal.currency, (totals.get(o.subtotal.currency) ?? 0) + Number(o.subtotal.amount));
  }
  return Array.from(totals, ([currency, total]) => ({ currency, total }));
}

function formatSum(sums: { currency: string; total: number }[]): string {
  return sums.map((s) => new Intl.NumberFormat("en-US", { style: "currency", currency: s.currency }).format(s.total)).join(" + ");
}

function OrderCard({ order, subsidiaryName, onClick }: { order: OperatorOrder; subsidiaryName: string; onClick: () => void }) {
  const lastAt = lastEventAt(order);
  return (
    <div className="kcard" onClick={onClick}>
      <div className="kcard__top">
        <span className="id">{order.orderId}</span>
      </div>
      <div className="kcard__amount">{formatMoney(order.subtotal)}</div>
      <div className="kcard__meta">
        <span className="kcard__reseller">
          <Users size={11} strokeWidth={2} />
          {order.tenantId}
        </span>
        {order.erpOrderId && <span className="mono">{order.erpOrderId}</span>}
      </div>
      {subsidiaryName && (
        <div className="kcard__sub">
          <Building2 size={11} strokeWidth={2} />
          {subsidiaryName}
        </div>
      )}
      {lastAt > 0 && <div className="kcard__foot">{timeAgo(new Date(lastAt).toISOString())}</div>}
    </div>
  );
}

function KanbanColumnView({
  column,
  orders,
  subsidiaryName,
  onCardClick,
}: {
  column: KanbanColumnDef;
  orders: OperatorOrder[];
  subsidiaryName: (o: OperatorOrder) => string;
  onCardClick: (o: OperatorOrder) => void;
}) {
  const sums = sumByCurrency(orders);
  return (
    <div className="kcol">
      <div className="kcol__head">
        <span className="kcol__label">{column.label}</span>
        <span className="kcol__count">{orders.length}</span>
      </div>
      {sums.length > 0 && <div className="kcol__sum">{formatSum(sums)}</div>}
      <div className="kcol__cards">
        {orders.length === 0 ? (
          <div className="kcol__empty">No orders</div>
        ) : (
          orders.map((o) => <OrderCard key={o.orderId} order={o} subsidiaryName={subsidiaryName(o)} onClick={() => onCardClick(o)} />)
        )}
      </div>
    </div>
  );
}

/** Grouped by lifecycle stage. Read-only by design, not just by omission — there is no
 * backend mutation to set an order's status (verified against operator/schema.py's
 * mutations), so progression only ever happens from the real ERP sync. Cards are plain
 * and click-only; no drag. */
export function KanbanBoard({
  orders,
  subsidiaryName,
  onCardClick,
}: {
  orders: OperatorOrder[];
  subsidiaryName: (o: OperatorOrder) => string;
  onCardClick: (o: OperatorOrder) => void;
}) {
  const grouped = new Map<string, OperatorOrder[]>();
  for (const col of COLUMNS) grouped.set(col.key, []);
  for (const o of orders) {
    const col = columnOf(o.status);
    if (col) grouped.get(col.key)!.push(o);
  }
  for (const list of grouped.values()) list.sort((a, b) => lastEventAt(b) - lastEventAt(a));

  return (
    <div className="kboard">
      {COLUMNS.map((col) => (
        <KanbanColumnView
          key={col.key}
          column={col}
          orders={grouped.get(col.key) ?? []}
          subsidiaryName={subsidiaryName}
          onCardClick={onCardClick}
        />
      ))}
    </div>
  );
}
