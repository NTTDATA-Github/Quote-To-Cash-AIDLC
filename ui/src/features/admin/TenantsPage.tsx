import { useState, type FormEvent } from "react";

import { DataTable, type Column } from "../../components/DataTable";
import { InfoTag } from "../../components/InfoTag";
import { StatusBadge } from "../../components/StatusBadge";
import { useBindings, useConnections, useCreateBinding, useRemoveBinding, useVerifyBinding } from "../../hooks/useAdmin";
import type { Binding } from "../../api/queries/admin";

export function TenantsPage() {
  const { data: bindings, isLoading, error } = useBindings();
  const { data: connections } = useConnections();
  const createBinding = useCreateBinding();
  const verifyBinding = useVerifyBinding();
  const removeBinding = useRemoveBinding();
  const [form, setForm] = useState({ tenantId: "", connectionId: "", erpCustomerId: "" });
  const [showForm, setShowForm] = useState(false);

  const columns: Column<Binding>[] = [
    { key: "tenant", header: "Tenant ID", render: (b) => <span className="id">{b.tenantId}</span> },
    { key: "connection", header: "Connection", render: (b) => b.connectionId },
    { key: "customer", header: "ERP customer ID", render: (b) => <span className="mono">{b.erpCustomerId}</span> },
    { key: "status", header: "Status", render: (b) => <StatusBadge status={b.status} /> },
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
    setForm({ tenantId: "", connectionId: "", erpCustomerId: "" });
    setShowForm(false);
  }

  return (
    <>
      <div className="pagehead">
        <div>
          <h1>Resellers</h1>
          <p>Each reseller is a tenant with a customer link into every ERP connection it buys from.</p>
        </div>
        <div className="actions">
          <button className="erp-btn erp-btn--primary" type="button" onClick={() => setShowForm((v) => !v)}>
            {showForm ? "Cancel" : "Link reseller to connection"}
          </button>
        </div>
      </div>
      {showForm && (
        <form className="panel stack" onSubmit={handleSubmit}>
          <div className="grid2">
            <div className="field">
              <label htmlFor="tenantId">Tenant ID</label>
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
      {error && <div className="callout callout--danger">Could not load resellers: {error.message}</div>}
      <DataTable columns={columns} rows={bindings ?? []} rowKey={(b) => b.bindingId} isLoading={isLoading} emptyMessage="No resellers linked yet" />
    </>
  );
}
