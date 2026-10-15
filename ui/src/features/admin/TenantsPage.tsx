import { useState, type FormEvent } from "react";
import { Search } from "lucide-react";

import { DataTable, type Column } from "../../components/DataTable";
import { FilterMenu } from "../../components/FilterMenu";
import { InfoTag } from "../../components/InfoTag";
import { PageHeader } from "../../components/PageHeader";
import { StatusBadge } from "../../components/StatusBadge";
import { useBindings, useConnections, useCreateBinding, useRemoveBinding, useResellers, useVerifyBinding } from "../../hooks/useAdmin";
import type { Binding } from "../../api/queries/admin";
import { statusLabel } from "../../lib/statusLabel";

const STATUS_FILTERS = ["all", "TO_VERIFY", "VERIFIED", "REMOVED"] as const;
const STATUS_OPTIONS = STATUS_FILTERS.map((s) => ({ value: s, label: s === "all" ? "All" : statusLabel(s) }));

export function TenantsPage() {
  const { data: bindings, isLoading, error } = useBindings();
  const { data: connections } = useConnections();
  const { data: resellers } = useResellers();
  const createBinding = useCreateBinding();
  const verifyBinding = useVerifyBinding();
  const removeBinding = useRemoveBinding();
  const [form, setForm] = useState({ tenantId: "", connectionId: "", erpCustomerId: "", name: "" });
  const [showForm, setShowForm] = useState(false);
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState<(typeof STATUS_FILTERS)[number]>("all");

  const resellerNameById = new Map((resellers ?? []).map((r) => [r.tenantId, r.name]));

  const rows = (bindings ?? [])
    .filter((b) => status === "all" || b.status === status)
    .filter((b) =>
      [b.tenantId, resellerNameById.get(b.tenantId) ?? "", b.connectionId, b.erpCustomerId].join(" ").toLowerCase().includes(search.toLowerCase()),
    );

  const columns: Column<Binding>[] = [
    {
      key: "tenant",
      header: "Reseller",
      render: (b) => resellerNameById.get(b.tenantId) ?? b.tenantId,
      sortValue: (b) => resellerNameById.get(b.tenantId) ?? b.tenantId,
    },
    { key: "tenantId", header: "Reseller ID", render: (b) => <span className="id">{b.tenantId}</span>, sortValue: (b) => b.tenantId },
    { key: "connection", header: "Connection", render: (b) => b.connectionId, sortValue: (b) => b.connectionId },
    { key: "customer", header: "ERP customer ID", render: (b) => <span className="mono">{b.erpCustomerId}</span>, sortValue: (b) => b.erpCustomerId },
    { key: "status", header: "Status", render: (b) => <StatusBadge status={statusLabel(b.status)} />, sortValue: (b) => b.status },
    {
      key: "actions",
      header: "",
      render: (b) =>
        b.status === "REMOVED" ? null : (
          <span className="actions">
            {b.status !== "VERIFIED" && (
              <button className="erp-btn erp-btn--secondary erp-btn--sm" type="button" onClick={() => verifyBinding.mutate({ bindingId: b.bindingId })}>
                Verify
              </button>
            )}
            <button className="erp-btn erp-btn--ghost erp-btn--sm" type="button" onClick={() => removeBinding.mutate({ bindingId: b.bindingId })}>
              Remove
            </button>
          </span>
        ),
    },
  ];

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    await createBinding.mutateAsync(form);
    setForm({ tenantId: "", connectionId: "", erpCustomerId: "", name: "" });
    setShowForm(false);
  }

  return (
    <>
      <PageHeader
        title="Resellers"
        subtitle="Each reseller has a customer link into every ERP connection it buys from."
        actions={
          <button className="erp-btn erp-btn--primary" type="button" onClick={() => setShowForm((v) => !v)}>
            {showForm ? "Cancel" : "Link reseller to connection"}
          </button>
        }
      />
      {showForm && (
        <form className="panel stack" onSubmit={handleSubmit}>
          <div className="grid2">
            <div className="field">
              <label htmlFor="name">Reseller name</label>
              <input className="input" id="name" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} required />
            </div>
            <div className="field">
              <label htmlFor="tenantId">
                Reseller ID <InfoTag text="The stable internal id for this reseller — never shown as the primary label, only the name is." />
              </label>
              <input className="input" id="tenantId" value={form.tenantId} onChange={(e) => setForm({ ...form, tenantId: e.target.value })} required />
            </div>
            <div className="field">
              <label htmlFor="connectionId">Connection</label>
              <select className="input" id="connectionId" value={form.connectionId} onChange={(e) => setForm({ ...form, connectionId: e.target.value })} required>
                <option value="">Select a connection</option>
                {(connections ?? []).map((c) => (
                  <option key={c.connectionId} value={c.connectionId}>
                    {c.instanceLabel} ({c.connectionId})
                  </option>
                ))}
              </select>
            </div>
            <div className="field">
              <label htmlFor="erpCustomerId">
                ERP customer ID <InfoTag text="The reseller's customer record ID inside this ERP connection — operator-only, never shown to the reseller." />
              </label>
              <input
                className="input"
                id="erpCustomerId"
                value={form.erpCustomerId}
                onChange={(e) => setForm({ ...form, erpCustomerId: e.target.value })}
                required
              />
            </div>
          </div>
          {createBinding.error && <div className="callout callout--danger">{(createBinding.error as Error).message}</div>}
          <div className="actions">
            <button className="erp-btn erp-btn--primary" type="submit" disabled={createBinding.isPending}>
              {createBinding.isPending ? "Saving…" : "Create link"}
            </button>
          </div>
        </form>
      )}
      <div className="toolbar">
        <div className="search-input">
          <Search size={15} strokeWidth={2} className="search-input__icon" />
          <input
            className="input"
            type="search"
            placeholder="Search by reseller, connection, or ERP customer id"
            style={{ width: 300 }}
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>
        <FilterMenu groups={[{ label: "Status", options: STATUS_OPTIONS, value: status, onChange: (v) => setStatus(v as (typeof STATUS_FILTERS)[number]) }]} />
      </div>
      {error && <div className="callout callout--danger">Could not load resellers: {error.message}</div>}
      <DataTable columns={columns} rows={rows} rowKey={(b) => b.bindingId} isLoading={isLoading} emptyMessage="No resellers match this filter" pageSize={10} />
    </>
  );
}
