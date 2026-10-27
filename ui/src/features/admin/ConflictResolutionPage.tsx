import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { Search } from "lucide-react";

import { DataTable, type Column } from "../../components/DataTable";
import { Drawer } from "../../components/Drawer";
import { PageHeader } from "../../components/PageHeader";
import { StatusBadge } from "../../components/StatusBadge";
import {
  useConflictExplanation,
  useOrderConflicts,
  useResellers,
  useSetSeverityRule,
  useSeverityRules,
} from "../../hooks/useAdmin";
import type { ConflictCategory, OrderConflict } from "../../api/queries/admin";
import { statusLabel } from "../../lib/statusLabel";

type StateFilter = "all" | "OPEN" | "IN_REVIEW" | "RESOLVED" | "DISMISSED";
type CategoryFilter = ConflictCategory | "all";

const OPEN_STATES = new Set(["OPEN", "IN_REVIEW"]);

// Plain-language names and one-line meanings, in the order they appear on the page.
const CATEGORIES: Record<ConflictCategory, { label: string; meaning: string }> = {
  CUSTOMER_ON_HOLD: { label: "Customer on hold", meaning: "The customer's account is blocked in the ERP." },
  PRODUCT_NOT_FOUND: { label: "Product not found", meaning: "The ERP does not recognise a product on the order." },
  PRICE_MISMATCH: { label: "Price mismatch", meaning: "The price on the order differs from the ERP's price list." },
  ADDRESS_PROBLEM: { label: "Shipping address rejected", meaning: "The ERP refused the delivery address." },
  DUPLICATE_ORDER: { label: "Duplicate order", meaning: "The ERP already has this order." },
  ERP_UNREACHABLE: { label: "ERP unreachable", meaning: "The ERP could not be reached. Orders retry automatically." },
  OTHER: { label: "Other", meaning: "The ERP's message does not match a known cause. Read the details." },
};
const CATEGORY_ORDER = Object.keys(CATEGORIES) as ConflictCategory[];

type Severity = OrderConflict["severity"];
const SEVERITY_LABEL: Record<Severity, string> = { HIGH: "High", MEDIUM: "Medium", LOW: "Low" };
const SEVERITY_TONE: Record<Severity, "danger" | "warning" | "neutral"> = {
  HIGH: "danger",
  MEDIUM: "warning",
  LOW: "neutral",
};
const SEVERITY_RANK: Record<Severity, number> = { HIGH: 0, MEDIUM: 1, LOW: 2 };

/** The most serious severity among some conflicts. */
function worstSeverity(conflicts: OrderConflict[]): Severity {
  return conflicts.reduce<Severity>(
    (worst, c) => (SEVERITY_RANK[c.severity] < SEVERITY_RANK[worst] ? c.severity : worst),
    "LOW",
  );
}

/** "2h 15m", "1d 3h", "40m": the largest two units, for a countdown a person can read. */
function formatSpan(ms: number): string {
  const minutes = Math.max(0, Math.round(ms / 60_000));
  if (minutes < 60) return `${minutes}m`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ${minutes % 60}m`;
  return `${Math.floor(hours / 24)}d ${hours % 24}h`;
}

/** What the deadline column says for one conflict at a given moment. */
function deadline(conflict: OrderConflict, now: number): { text: string; overdue: boolean } {
  if (!OPEN_STATES.has(conflict.status)) return { text: "Closed", overdue: false };
  const remaining = new Date(conflict.slaDueAt).getTime() - now;
  if (remaining < 0) return { text: `Overdue by ${formatSpan(-remaining)}`, overdue: true };
  return { text: `Due in ${formatSpan(remaining)}`, overdue: false };
}

/** The median of a list of numbers, or null for an empty list. */
function median(values: number[]): number | null {
  if (values.length === 0) return null;
  const sorted = [...values].sort((a, b) => a - b);
  const mid = Math.floor(sorted.length / 2);
  return sorted.length % 2 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2;
}

function formatWhen(iso: string): string {
  return new Date(iso).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

/** How urgent each cause is. Operators change it here; it applies to conflicts opened from now on. */
function SeverityRulesEditor() {
  const { data: rules, isLoading, error } = useSeverityRules();
  const save = useSetSeverityRule();
  const options: Severity[] = ["HIGH", "MEDIUM", "LOW"];
  return (
    <details className="panel stack">
      <summary style={{ cursor: "pointer", font: "600 15px/24px var(--font-sans)" }}>Severity rules</summary>
      <p className="muted" style={{ margin: 0 }}>
        How urgent each cause is. A rejected order and an order still being retried can have different urgency.
        Changes apply to conflicts opened from now on.
      </p>
      {isLoading && <p className="muted">Loading…</p>}
      {error && <div className="callout callout--danger">Could not load the rules: {error.message}</div>}
      {rules && (
        <div className="erp-table-wrap">
          <table className="erp-table">
            <thead>
              <tr>
                <th>Cause</th>
                <th>When the ERP rejects it</th>
                <th>While it is being retried</th>
              </tr>
            </thead>
            <tbody>
              {rules.map((rule) => (
                <tr key={rule.category}>
                  <td>{rule.label}</td>
                  <td>
                    <select
                      className="input"
                      aria-label={`${rule.label}: when rejected`}
                      value={rule.whenRejected}
                      disabled={save.isPending}
                      onChange={(e) =>
                        save.mutate({ category: rule.category, whenRejected: e.target.value, whenRetrying: rule.whenRetrying })
                      }
                    >
                      {options.map((o) => (
                        <option key={o} value={o}>{SEVERITY_LABEL[o]}</option>
                      ))}
                    </select>
                  </td>
                  <td>
                    <select
                      className="input"
                      aria-label={`${rule.label}: while retrying`}
                      value={rule.whenRetrying}
                      disabled={save.isPending}
                      onChange={(e) =>
                        save.mutate({ category: rule.category, whenRejected: rule.whenRejected, whenRetrying: e.target.value })
                      }
                    >
                      {options.map((o) => (
                        <option key={o} value={o}>{SEVERITY_LABEL[o]}</option>
                      ))}
                    </select>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </details>
  );
}

/** One card per kind of problem, over the open conflicts of that kind. */
interface Group {
  category: ConflictCategory;
  open: OrderConflict[];
  overdue: number;
  resellers: string[];
  oldestOpenedAt: number;
  worst: Severity;
}

/** An operator's "what's wrong" area: causes that need a look, then the full list. */
export function ConflictResolutionPage() {
  const [state, setState] = useState<StateFilter>("all");
  const [category, setCategory] = useState<CategoryFilter>("all");
  const [search, setSearch] = useState("");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  // One fetch; everything on the page is derived from this list.
  const { data: conflicts, isLoading, error } = useOrderConflicts(null);
  const { data: resellers } = useResellers();
  const explanation = useConflictExplanation(selectedId);

  const now = Date.now();
  const all = useMemo(() => conflicts ?? [], [conflicts]);
  const resellerName = (tenantId: string) => (resellers ?? []).find((r) => r.tenantId === tenantId)?.name ?? tenantId;
  const isOpen = (c: OrderConflict) => OPEN_STATES.has(c.status);

  const groups: Group[] = useMemo(() => {
    const byCategory = new Map<ConflictCategory, OrderConflict[]>();
    for (const c of all) {
      if (!isOpen(c)) continue;
      byCategory.set(c.category, [...(byCategory.get(c.category) ?? []), c]);
    }
    return CATEGORY_ORDER.filter((k) => byCategory.has(k))
      .map((k) => {
        const open = byCategory.get(k) ?? [];
        return {
          category: k,
          open,
          overdue: open.filter((c) => deadline(c, now).overdue).length,
          resellers: [...new Set(open.map((c) => resellerName(c.tenantId)))],
          oldestOpenedAt: Math.min(...open.map((c) => new Date(c.openedAt).getTime())),
          worst: worstSeverity(open),
        };
      })
      // Overdue causes first, then the biggest.
      .sort((a, b) => b.overdue - a.overdue || b.open.length - a.open.length);
  }, [all, resellers, now]);

  const openList = all.filter(isOpen);
  const overdueCount = openList.filter((c) => deadline(c, now).overdue).length;
  const medianAgeHours = median(openList.map((c) => (now - new Date(c.openedAt).getTime()) / 3_600_000));
  const recovered = all.filter((c) => c.status === "RESOLVED").length;

  const counts: Record<StateFilter, number> = {
    all: all.length,
    OPEN: all.filter((c) => c.status === "OPEN").length,
    IN_REVIEW: all.filter((c) => c.status === "IN_REVIEW").length,
    RESOLVED: all.filter((c) => c.status === "RESOLVED").length,
    DISMISSED: all.filter((c) => c.status === "DISMISSED").length,
  };

  const rows = all
    .filter((c) => state === "all" || c.status === state)
    .filter((c) => category === "all" || c.category === category)
    .filter((c) =>
      [c.orderId, resellerName(c.tenantId), c.reason, CATEGORIES[c.category].label].join(" ").toLowerCase().includes(search.toLowerCase()),
    );

  const selected = all.find((c) => c.conflictId === selectedId) ?? null;

  function showCategory(next: ConflictCategory) {
    setCategory(next);
    setState("all");
    document.getElementById("all-conflicts")?.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  const columns: Column<OrderConflict>[] = [
    { key: "order", header: "Order", render: (c) => <span className="id">{c.orderId}</span>, sortValue: (c) => c.orderId },
    { key: "reseller", header: "Reseller", render: (c) => resellerName(c.tenantId), sortValue: (c) => resellerName(c.tenantId) },
    {
      key: "problem",
      header: "Problem",
      render: (c) => (
        <span className="cell-stack">
          <b>
            {CATEGORIES[c.category].label}
            {c.categorySource === "AI" && <span className="erp-badge erp-badge--neutral" style={{ marginLeft: 6 }}>AI</span>}
          </b>
          <span className="muted" style={{ fontSize: 12 }}>{c.reason}</span>
        </span>
      ),
      sortValue: (c) => CATEGORIES[c.category].label,
    },
    {
      key: "severity",
      header: "Severity",
      render: (c) => <span className={`erp-badge erp-badge--${SEVERITY_TONE[c.severity]}`}>{SEVERITY_LABEL[c.severity]}</span>,
      sortValue: (c) => (c.severity === "HIGH" ? 0 : 1),
    },
    { key: "status", header: "Status", render: (c) => <StatusBadge status={statusLabel(c.status)} />, sortValue: (c) => c.status },
    { key: "attempts", header: "Attempts", align: "right", render: (c) => c.attempts, sortValue: (c) => c.attempts },
    {
      key: "deadline",
      header: "Deadline",
      render: (c) => {
        const d = deadline(c, now);
        return <span className={d.overdue ? "erp-badge erp-badge--danger" : "muted"}>{d.text}</span>;
      },
      sortValue: (c) => new Date(c.slaDueAt).getTime(),
    },
  ];

  const stateTiles: { value: StateFilter; label: string; dot: string }[] = [
    { value: "all", label: "All", dot: "neutral" },
    { value: "OPEN", label: "Open", dot: "warning" },
    { value: "IN_REVIEW", label: "In review", dot: "neutral" },
    { value: "RESOLVED", label: "Resolved", dot: "success" },
    { value: "DISMISSED", label: "Dismissed", dot: "neutral" },
  ];

  return (
    <>
      <PageHeader
        title="Conflict resolution"
        subtitle="Orders the ERP rejected, or could not receive. They are grouped by cause, so one fix can clear many orders."
      />

      <div className="statgrid">
        <div className="stat">
          <b>{openList.length}</b>
          <span>Open now</span>
        </div>
        <div className="stat">
          <b style={overdueCount > 0 ? { color: "var(--status-danger-fg)" } : undefined}>{overdueCount}</b>
          <span>Past deadline</span>
        </div>
        <div className="stat">
          <b>{groups.length}</b>
          <span>Causes to look at</span>
        </div>
        <div className="stat">
          <b>{medianAgeHours === null ? "—" : `${medianAgeHours < 1 ? "<1" : Math.round(medianAgeHours)}h`}</b>
          <span>Median age of open</span>
        </div>
      </div>

      <section className="panel stack" aria-labelledby="causes-heading">
        <div className="panel-head">
          <h2 id="causes-heading">What needs fixing</h2>
          <span className="muted">{recovered} recovered on a retry</span>
        </div>
        {isLoading && <p className="muted">Loading…</p>}
        {error && <div className="callout callout--danger">Could not load conflicts: {error.message}</div>}
        {!isLoading && !error && groups.length === 0 && (
          <p className="muted">Nothing needs fixing. Every order is reaching its ERP.</p>
        )}
        {groups.length > 0 && (
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(260px, 1fr))", gap: "var(--space-3)" }}>
            {groups.map((g) => {
              const active = category === g.category;
              return (
                <article
                  key={g.category}
                  className="stat"
                  style={{ borderColor: active ? "var(--brand)" : undefined, gap: "var(--space-2)" }}
                  aria-label={CATEGORIES[g.category].label}
                >
                  <div style={{ display: "flex", justifyContent: "space-between", gap: "var(--space-2)", alignItems: "center" }}>
                    <b style={{ font: "600 15px/22px var(--font-sans)" }}>{CATEGORIES[g.category].label}</b>
                    <span className={`erp-badge erp-badge--${SEVERITY_TONE[g.worst]}`}>{SEVERITY_LABEL[g.worst]}</span>
                  </div>
                  <span className="muted" style={{ fontSize: 13 }}>{CATEGORIES[g.category].meaning}</span>
                  <div style={{ display: "flex", alignItems: "baseline", gap: "var(--space-2)" }}>
                    <b style={{ font: "600 24px/32px var(--font-sans)" }}>{g.open.length}</b>
                    <span className="muted">{g.open.length === 1 ? "order" : "orders"}</span>
                    {g.overdue > 0 && <span className="erp-badge erp-badge--danger">{g.overdue} overdue</span>}
                  </div>
                  <span className="muted" style={{ fontSize: 12 }}>
                    {g.resellers.join(", ")} · oldest {formatSpan(now - g.oldestOpenedAt)}
                  </span>
                  <button
                    className="erp-btn erp-btn--secondary erp-btn--sm"
                    type="button"
                    aria-pressed={active}
                    onClick={() => showCategory(g.category)}
                  >
                    {active ? "Showing these orders" : "View orders"}
                  </button>
                </article>
              );
            })}
          </div>
        )}
      </section>

      <SeverityRulesEditor />

      <section className="panel stack" id="all-conflicts" aria-labelledby="all-heading">
        <div className="panel-head">
          <h2 id="all-heading">All conflicts</h2>
          {category !== "all" && (
            <button className="erp-btn erp-btn--ghost erp-btn--sm" type="button" onClick={() => setCategory("all")}>
              Showing: {CATEGORIES[category].label} · Clear
            </button>
          )}
        </div>

        <div className="filtertiles">
          {stateTiles.map((t) => (
            <button key={t.value} type="button" className="filtertile" aria-pressed={state === t.value} onClick={() => setState(t.value)}>
              <b>{counts[t.value]}</b>
              <span>
                <i className={`tiledot tiledot--${t.dot}`} aria-hidden="true" />
                {t.label}
              </span>
            </button>
          ))}
        </div>

        <div className="toolbar">
          <div className="search-input">
            <Search size={15} strokeWidth={2} className="search-input__icon" />
            <input
              className="input"
              type="search"
              placeholder="Search by order, reseller, or problem"
              style={{ width: 300 }}
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
          </div>
          <select
            className="input"
            aria-label="Filter by problem"
            style={{ width: 220 }}
            value={category}
            onChange={(e) => setCategory(e.target.value as CategoryFilter)}
          >
            <option value="all">All problems</option>
            {CATEGORY_ORDER.map((k) => (
              <option key={k} value={k}>
                {CATEGORIES[k].label}
              </option>
            ))}
          </select>
        </div>

        <DataTable
          columns={columns}
          rows={rows}
          rowKey={(c) => c.conflictId}
          isLoading={isLoading}
          emptyMessage={all.length === 0 ? "No conflicts. Every order is flowing to its ERP." : "No conflicts match this filter."}
          onRowClick={(c) => setSelectedId(c.conflictId)}
          pageSize={10}
        />
      </section>

      <Drawer open={selected !== null} onClose={() => setSelectedId(null)} title={selected ? `Conflict on ${selected.orderId}` : ""}>
        {selected && (
          <div className="stack">
            <div>
              <b style={{ font: "600 16px/24px var(--font-sans)" }}>{CATEGORIES[selected.category].label}</b>
              <p className="muted" style={{ margin: "4px 0 0" }}>{CATEGORIES[selected.category].meaning}</p>
              {selected.categorySource === "AI" && (
                <p className="muted" style={{ margin: "4px 0 0", fontSize: 12 }}>
                  No rule recognised this message, so AI suggested this cause. Check it before relying on the grouping.
                </p>
              )}
            </div>
            <dl className="kv">
              <dt>Reseller</dt>
              <dd>{resellerName(selected.tenantId)}</dd>
              <dt>ERP message</dt>
              <dd>{selected.reason}</dd>
              <dt>Reason code</dt>
              <dd className="mono">{selected.reasonCode}</dd>
              <dt>Severity</dt>
              <dd>
                <span className={`erp-badge erp-badge--${SEVERITY_TONE[selected.severity]}`}>{SEVERITY_LABEL[selected.severity]}</span>
              </dd>
              <dt>Status</dt>
              <dd>
                <StatusBadge status={statusLabel(selected.status)} />
              </dd>
              <dt>Attempts</dt>
              <dd>{selected.attempts}</dd>
              <dt>Opened</dt>
              <dd>{formatWhen(selected.openedAt)}</dd>
              <dt>Deadline</dt>
              <dd>{formatWhen(selected.slaDueAt)}</dd>
              {selected.resolvedAt && (
                <>
                  <dt>Closed</dt>
                  <dd>{formatWhen(selected.resolvedAt)}</dd>
                </>
              )}
              {selected.resolutionNote && (
                <>
                  <dt>Note</dt>
                  <dd>{selected.resolutionNote}</dd>
                </>
              )}
            </dl>

            <section className="stack" aria-label="Summary">
              <h3 style={{ margin: 0, font: "600 14px/20px var(--font-sans)" }}>AI summary</h3>
              {explanation.isFetching && <p className="muted">Writing a summary…</p>}
              {explanation.data?.text && (
                <>
                  <p style={{ margin: 0 }}>{explanation.data.text}</p>
                  <p className="muted" style={{ margin: 0, fontSize: 12 }}>
                    Written by AI from this conflict's facts. Check the order before you act on it.
                  </p>
                </>
              )}
              {!explanation.isFetching && explanation.data?.unavailable && (
                <p className="muted" style={{ margin: 0 }}>{explanation.data.unavailable}</p>
              )}
              {!explanation.isFetching && explanation.error && (
                <p className="muted" style={{ margin: 0 }}>The summary could not be loaded.</p>
              )}
              {!explanation.isFetching && (explanation.error || explanation.data?.unavailable) && (
                <div className="actions">
                  <button className="erp-btn erp-btn--secondary erp-btn--sm" type="button" onClick={() => void explanation.refetch()}>
                    Try again
                  </button>
                </div>
              )}
            </section>

            <div className="actions">
              {group(selected.category, all, isOpen) > 1 && (
                <button
                  className="erp-btn erp-btn--secondary"
                  type="button"
                  onClick={() => {
                    setSelectedId(null);
                    showCategory(selected.category);
                  }}
                >
                  Show all {group(selected.category, all, isOpen)} with this problem
                </button>
              )}
              <Link className="erp-btn erp-btn--secondary" to={`/admin/orders/${selected.orderId}`}>
                Open order
              </Link>
            </div>
          </div>
        )}
      </Drawer>
    </>
  );
}

/** How many open conflicts share one cause. */
function group(category: ConflictCategory, all: OrderConflict[], isOpen: (c: OrderConflict) => boolean): number {
  return all.filter((c) => isOpen(c) && c.category === category).length;
}
