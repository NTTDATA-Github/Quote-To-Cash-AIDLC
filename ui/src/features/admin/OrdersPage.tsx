import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { LayoutGrid, List, Search } from "lucide-react";

import { DataTable, type Column } from "../../components/DataTable";
import { StatusBadge } from "../../components/StatusBadge";
import { Drawer } from "../../components/Drawer";
import { FilterMenu } from "../../components/FilterMenu";
import { InfoTag } from "../../components/InfoTag";
import { KanbanBoard } from "../../components/KanbanBoard";
import { OrderDetailBody } from "../../components/OrderDetailBody";
import { PageHeader } from "../../components/PageHeader";
import { useOperatorOrders, useSubsidiaries } from "../../hooks/useAdmin";
import type { OperatorOrder } from "../../api/queries/admin";
import { statusLabel } from "../../lib/statusLabel";
import { orderStage, stageLabel, statusRank, type Stage } from "../../lib/orderStage";

const STAGE_FILTERS: (Stage | "all")[] = ["all", "in-flight", "completed", "attention"];
const STAGE_OPTIONS = STAGE_FILTERS.map((s) => ({ value: s, label: s === "all" ? "All" : stageLabel(s) }));

const STATUS_GLOSSARY =
  "Open → Confirmed → Closed. An order is read from the ERP, not created by this " +
  "platform. \"Reference\" is the reseller's own PO number, when the ERP has one. " +
  "\"ERP order\" is the ERP's own order id — it's there from the first poll, since " +
  "that's how the order was found.";

type View = "kanban" | "table";

/** Every order, across every tenant — the cross-tenant visibility an operator needs to
 * debug a specific reseller's order without knowing its id ahead of time. */
export function OrdersPage() {
  const { data: orders, isLoading, error } = useOperatorOrders();
  const { data: subsidiaries } = useSubsidiaries();
  const [search, setSearch] = useState("");
  const [params, setParams] = useSearchParams();
  const [openOrderId, setOpenOrderId] = useState<string | null>(null);
  const stageParam = params.get("stage");
  const stage: Stage | "all" = STAGE_FILTERS.includes(stageParam as Stage) ? (stageParam as Stage) : "all";
  const view: View = params.get("view") === "table" ? "table" : "kanban";
  const nameById = new Map((subsidiaries ?? []).map((s) => [s.subsidiaryId, s.name]));

  function subsidiaryName(order: OperatorOrder): string {
    const id = order.parties.subsidiaryId;
    if (!id) return "";
    return nameById.get(id) ?? id;
  }

  function setStage(next: Stage | "all") {
    const nextParams = new URLSearchParams(params);
    if (next === "all") nextParams.delete("stage");
    else nextParams.set("stage", next);
    setParams(nextParams, { replace: true });
  }

  function setView(next: View) {
    const nextParams = new URLSearchParams(params);
    if (next === "kanban") nextParams.delete("view");
    else nextParams.set("view", next);
    setParams(nextParams, { replace: true });
  }

  const filtered = (orders ?? []).filter((o) => {
    if (stage !== "all" && orderStage(o.status) !== stage) return false;
    const haystack = [o.orderId, o.tenantId, o.clientReference, subsidiaryName(o)].join(" ").toLowerCase();
    return haystack.includes(search.toLowerCase());
  });

  const openOrder = openOrderId ? (orders ?? []).find((o) => o.orderId === openOrderId) ?? null : null;

  const columns: Column<OperatorOrder>[] = [
    {
      key: "orderId",
      header: "Order",
      // Row click opens the quick-peek drawer; the id itself still links straight to the
      // full page — stopPropagation so clicking it doesn't also trigger the row's onClick.
      render: (o) => (
        <Link to={`/admin/orders/${o.orderId}`} onClick={(e) => e.stopPropagation()}>
          {o.orderId}
        </Link>
      ),
      sortValue: (o) => o.orderId,
    },
    { key: "tenant", header: "Reseller", render: (o) => <span className="id">{o.tenantId}</span>, sortValue: (o) => o.tenantId },
    { key: "ref", header: "Reference", render: (o) => o.clientReference, sortValue: (o) => o.clientReference },
    { key: "subsidiary", header: "Subsidiary", render: (o) => subsidiaryName(o) || "—", sortValue: (o) => subsidiaryName(o) },
    { key: "connection", header: "Connection", render: (o) => o.owningConnectionId ?? "—", sortValue: (o) => o.owningConnectionId },
    {
      key: "erpOrderId",
      header: "ERP order",
      render: (o) => (o.erpOrderId ? <span className="mono">{o.erpOrderId}</span> : "—"),
      sortValue: (o) => o.erpOrderId,
    },
    {
      key: "status",
      header: (
        <>
          Status <InfoTag text={STATUS_GLOSSARY} />
        </>
      ),
      render: (o) => <StatusBadge status={statusLabel(o.status)} />,
      sortValue: (o) => statusRank(o.status),
    },
  ];

  return (
    <>
      <PageHeader
        title="Orders"
        subtitle="Every order across every reseller — for debugging, not the reseller's own view."
        actions={
          <div className="viewtoggle" role="group" aria-label="View">
            <button
              type="button"
              className={`icon-btn ${view === "kanban" ? "is-active" : ""}`}
              aria-label="Kanban view"
              aria-pressed={view === "kanban"}
              onClick={() => setView("kanban")}
            >
              <LayoutGrid size={16} strokeWidth={2} />
            </button>
            <button
              type="button"
              className={`icon-btn ${view === "table" ? "is-active" : ""}`}
              aria-label="Table view"
              aria-pressed={view === "table"}
              onClick={() => setView("table")}
            >
              <List size={16} strokeWidth={2} />
            </button>
          </div>
        }
      />
      <div className="toolbar">
        <label className="sr" htmlFor="q">
          Search orders
        </label>
        <div className="search-input">
          <Search size={15} strokeWidth={2} className="search-input__icon" />
          <input
            className="input"
            id="q"
            type="search"
            placeholder="Search by order, tenant, reference, or subsidiary"
            style={{ width: 320 }}
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>
        <FilterMenu groups={[{ label: "Stage", options: STAGE_OPTIONS, value: stage, onChange: (v) => setStage(v as Stage | "all") }]} />
      </div>
      {error && <div className="callout callout--danger">Could not load orders: {error.message}</div>}
      {view === "kanban" ? (
        <KanbanBoard orders={filtered} subsidiaryName={subsidiaryName} onCardClick={(o) => setOpenOrderId(o.orderId)} />
      ) : (
        <DataTable
          columns={columns}
          rows={filtered}
          rowKey={(o) => o.orderId}
          isLoading={isLoading}
          emptyMessage="No orders match this filter"
          onRowClick={(o) => setOpenOrderId(o.orderId)}
          pageSize={10}
        />
      )}
      <Drawer
        open={!!openOrder}
        onClose={() => setOpenOrderId(null)}
        title={
          openOrder && (
            <>
              {openOrder.orderId} <StatusBadge status={statusLabel(openOrder.status)} />
            </>
          )
        }
        actions={
          openOrder && (
            <Link className="erp-btn erp-btn--secondary erp-btn--sm" to={`/admin/orders/${openOrder.orderId}`}>
              Open full page
            </Link>
          )
        }
      >
        {openOrder && <OrderDetailBody order={openOrder} subsidiaryName={subsidiaryName(openOrder)} />}
      </Drawer>
    </>
  );
}
