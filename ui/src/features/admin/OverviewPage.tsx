import { Link } from "react-router-dom";
import {
  Activity,
  AlertTriangle,
  ArrowRight,
  ArrowRightLeft,
  Bell,
  Building2,
  CircleCheck,
  PackageCheck,
  Plug,
  ShoppingCart,
  Users,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";

import { DataTable, type Column } from "../../components/DataTable";
import { PageHeader } from "../../components/PageHeader";
import { StatusBadge, statusRole, type Role } from "../../components/StatusBadge";
import {
  useBindings,
  useConnections,
  useNotifications,
  useOperatorOrders,
  useResellers,
  useSubsidiaries,
} from "../../hooks/useAdmin";
import type { OperatorOrder } from "../../api/queries/admin";
import { statusLabel } from "../../lib/statusLabel";
import { orderStage } from "../../lib/orderStage";
import { timeAgo } from "../../lib/timeAgo";

type TileTone = "brand" | "progress" | "success" | "warning" | "danger" | "accent";

function StatTile(props: {
  to?: string;
  icon: LucideIcon;
  tone: TileTone;
  value: number | string;
  label: string;
  hint?: string;
}) {
  const { to, icon: Icon, tone, value, label, hint } = props;
  const body = (
    <>
      <div className="tile__top">
        <span className={`tile__icon tile__icon--${tone}`}>
          <Icon size={18} strokeWidth={2} />
        </span>
        {to && <ArrowRight size={16} strokeWidth={2} className="muted" />}
      </div>
      <div className="tile__value">{value}</div>
      <div className="tile__label">{label}</div>
      {hint && <div className="tile__hint">{hint}</div>}
    </>
  );
  if (to) {
    return (
      <Link to={to} className="tile tile--link">
        {body}
      </Link>
    );
  }
  return <div className="tile">{body}</div>;
}

// Live orders are adopted straight from the ERP into SENT_TO_ERP (domain/aggregate.py
// OrderObserved) and FULFILLED left the order lifecycle entirely (FR-A6) — it's a
// fulfillment score now, not a stage. Open -> Confirmed -> Closed is what's left.
const PIPELINE: { name: string; labels: string[]; tone: Exclude<Role, "warning"> }[] = [
  { name: "Open", labels: ["Open"], tone: "progress" },
  { name: "Confirmed", labels: ["Confirmed"], tone: "progress" },
  { name: "Closed", labels: ["Closed"], tone: "success" },
];

export function OverviewPage() {
  const { data: orders = [], isLoading } = useOperatorOrders();
  const { data: connections = [] } = useConnections();
  const { data: bindings = [] } = useBindings();
  const { data: subsidiaries = [] } = useSubsidiaries();
  const { data: resellerNames = [] } = useResellers();
  const { data: notifications = [] } = useNotifications();

  const labelled = orders.map((o) => ({ order: o, label: statusLabel(o.status), role: statusRole(statusLabel(o.status)), stage: orderStage(o.status) }));
  const inFlight = labelled.filter((x) => x.stage === "in-flight").length;
  const completed = labelled.filter((x) => x.stage === "completed").length;
  const attention = labelled.filter((x) => x.stage === "attention");
  const activeConnections = connections.filter((c) => c.status.toUpperCase() === "ACTIVE").length;
  const resellerCount = new Set(bindings.map((b) => b.tenantId)).size;
  const resellerNameById = new Map(resellerNames.map((r) => [r.tenantId, r.name]));
  const resellerName = (tenantId: string) => resellerNameById.get(tenantId) ?? tenantId;
  const failedNotifications = notifications.filter((n) => statusRole(statusLabel(n.status)) === "danger");

  const stageCounts = PIPELINE.map((s) => ({
    ...s,
    count: labelled.filter((x) => s.labels.includes(x.label)).length,
  }));
  const total = orders.length || 1;

  // "Recent" means something specific: the order's own last status change, not
  // whatever order the API happened to return rows in (the projection has no
  // created/updated column to sort by at the source — this sorts client-side off
  // each order's own timeline instead of silently trusting row order).
  function latestEvent(o: OperatorOrder): { status: string; occurredAt: string } | null {
    return o.timeline.reduce<{ status: string; occurredAt: string } | null>(
      (latest, t) => (!latest || new Date(t.occurredAt) > new Date(latest.occurredAt) ? t : latest),
      null,
    );
  }
  const recent = [...orders]
    .sort((a, b) => new Date(latestEvent(b)?.occurredAt ?? 0).getTime() - new Date(latestEvent(a)?.occurredAt ?? 0).getTime())
    .slice(0, 6);
  const recentColumns: Column<OperatorOrder>[] = [
    { key: "orderId", header: "Order", render: (o) => <Link to={`/admin/orders/${o.orderId}`}>{o.orderId}</Link> },
    { key: "tenant", header: "Reseller", render: (o) => resellerName(o.tenantId) },
    { key: "status", header: "Status", render: (o) => <StatusBadge status={statusLabel(o.status)} /> },
    { key: "updated", header: "Last activity", render: (o) => (latestEvent(o) ? timeAgo(latestEvent(o)!.occurredAt) : "—") },
  ];

  return (
    <>
      <PageHeader title="Dashboard" />
      <section className="hero">
        <div className="hero__brand">
          <span className="hero__mark">
            <ArrowRightLeft size={14} strokeWidth={2.25} />
          </span>
          <span className="hero__eyebrow">Order-to-Cash Connector</span>
        </div>
        <h1>Operator Console</h1>
        <p>
          One place to run order-to-cash across your resellers. The connector takes reseller orders, routes each to the
          right ERP, and tracks every step from submitted to fulfilled — so you can watch flow, link customers, and clear
          problems without logging into each ERP.
        </p>
        <div className="hero__facts">
          <span className="hero__fact">
            <ShoppingCart size={15} strokeWidth={2} /> <b>{orders.length}</b> orders
          </span>
          <span className="hero__fact">
            <Plug size={15} strokeWidth={2} /> <b>{activeConnections}</b> active ERP connections
          </span>
          <span className="hero__fact">
            <Users size={15} strokeWidth={2} /> <b>{resellerCount}</b> resellers
          </span>
          <span className="hero__fact">
            <Building2 size={15} strokeWidth={2} /> <b>{subsidiaries.length}</b> subsidiaries
          </span>
        </div>
      </section>

      <div className="tiles">
        <StatTile to="/admin/orders" icon={ShoppingCart} tone="brand" value={orders.length} label="Total orders" hint="Across every reseller" />
        <StatTile to="/admin/orders?stage=in-flight" icon={Activity} tone="progress" value={inFlight} label="In flight" hint="Open or confirmed" />
        <StatTile to="/admin/orders?stage=completed" icon={PackageCheck} tone="success" value={completed} label="Completed" hint="Closed" />
        <StatTile
          to="/admin/conflict-resolution"
          icon={AlertTriangle}
          tone={attention.length ? "danger" : "success"}
          value={attention.length}
          label="Needs attention"
          hint="Cancelled"
        />
      </div>

      <section className="panel">
        <div className="panel-head">
          <div>
            <h2 className="section-title">
              <Activity size={16} strokeWidth={2} /> Order pipeline
            </h2>
            <p className="section-sub">Where every order sits in the lifecycle right now.</p>
          </div>
        </div>
        <div className="pipeline">
          {stageCounts.map((s) => (
            <div key={s.name} className={`pipe-stage pipe-stage--${s.tone}`}>
              <div className="pipe-stage__head">
                <span className="pipe-stage__name">{s.name}</span>
              </div>
              <span className="pipe-stage__count">{s.count}</span>
              <span className="pipe-stage__bar">
                <span className="pipe-stage__fill" style={{ width: `${Math.round((s.count / total) * 100)}%` }} />
              </span>
            </div>
          ))}
        </div>
      </section>

      <div className="dash-split">
        <section className="panel">
          <div className="panel-head">
            <div>
              <h2 className="section-title">
                <ShoppingCart size={16} strokeWidth={2} /> Recently updated
              </h2>
              <p className="section-sub">By last status change, newest first.</p>
            </div>
            <Link className="erp-btn erp-btn--ghost erp-btn--sm" to="/admin/orders">
              View all <ArrowRight size={14} strokeWidth={2} />
            </Link>
          </div>
          <DataTable
            columns={recentColumns}
            rows={recent}
            rowKey={(o) => o.orderId}
            isLoading={isLoading}
            emptyMessage="No orders yet"
          />
        </section>

        <section className="panel">
          <div className="panel-head">
            <h2 className="section-title">
              <AlertTriangle size={16} strokeWidth={2} /> Needs attention
            </h2>
          </div>
          <div className="attn">
            {attention.length === 0 && failedNotifications.length === 0 ? (
              <div className="attn__ok">
                <CircleCheck size={18} strokeWidth={2} /> Everything is flowing. Nothing needs you.
              </div>
            ) : (
              <>
                {attention.slice(0, 5).map((x) => (
                  <Link key={x.order.orderId} to={`/admin/orders/${x.order.orderId}`} className="attn__row" style={{ textDecoration: "none" }}>
                    <span className={`attn__icon${x.role === "warning" ? " attn__icon--warning" : ""}`}>
                      <AlertTriangle size={15} strokeWidth={2} />
                    </span>
                    <span className="attn__main">
                      <span className="attn__title">
                        Order <span className="id">{x.order.orderId}</span>
                      </span>
                      <span className="attn__meta">
                        {x.label} · reseller {resellerName(x.order.tenantId)}
                      </span>
                    </span>
                    <StatusBadge status={x.label} />
                  </Link>
                ))}
                {failedNotifications.slice(0, 3).map((n) => (
                  <div key={n.deliveryId} className="attn__row">
                    <span className="attn__icon">
                      <Bell size={15} strokeWidth={2} />
                    </span>
                    <span className="attn__main">
                      <span className="attn__title">Notification failed</span>
                      <span className="attn__meta">
                        {n.eventType} · order {n.orderId} · {n.attempts} attempts
                      </span>
                    </span>
                    <StatusBadge status={statusLabel(n.status)} />
                  </div>
                ))}
              </>
            )}
          </div>
        </section>
      </div>
    </>
  );
}
