import { useState, type FormEvent } from "react";

import { DataTable, type Column } from "../../components/DataTable";
import { InfoTag } from "../../components/InfoTag";
import { StatusBadge } from "../../components/StatusBadge";
import { useConnections, usePauseConnection, useRegisterConnection, useResumeConnection } from "../../hooks/useAdmin";
import type { Connection } from "../../api/queries/admin";

const EMPTY_FORM = { erpType: "odoo", instanceLabel: "", baseUrl: "", database: "", username: "", secretRef: "", webhookSecretRef: "" };

export function ConnectionsPage() {
  const { data: connections, isLoading, error } = useConnections();
  const registerConnection = useRegisterConnection();
  const pauseConnection = usePauseConnection();
  const resumeConnection = useResumeConnection();
  const [form, setForm] = useState(EMPTY_FORM);
  const [showForm, setShowForm] = useState(false);

  const columns: Column<Connection>[] = [
    { key: "id", header: "Connection", render: (c) => <span className="id">{c.connectionId}</span> },
    { key: "label", header: "Label", render: (c) => c.instanceLabel },
    { key: "erp", header: "ERP", render: (c) => c.erpType },
    { key: "status", header: "Status", render: (c) => <StatusBadge status={c.status} /> },
    { key: "webhook", header: "Webhook secret", render: (c) => (c.hasWebhookSecret ? "Configured" : "Not set") },
    {
      key: "actions",
      header: "",
      render: (c) =>
        c.status === "ACTIVE" ? (
          <button
            className="erp-btn erp-btn--ghost erp-btn--sm"
            type="button"
            onClick={() => pauseConnection.mutate({ connectionId: c.connectionId })}
          >
            Pause
          </button>
        ) : (
          <button
            className="erp-btn erp-btn--ghost erp-btn--sm"
            type="button"
            onClick={() => resumeConnection.mutate({ connectionId: c.connectionId })}
          >
            Resume
          </button>
        ),
    },
  ];

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    const { database, username, ...rest } = form;
    await registerConnection.mutateAsync({
      ...rest,
      // Odoo-shaped fields today, packed generically — a future ERP's connection form
      // sends whatever credentials it actually needs; the backend has no fixed shape.
      credentials: { database, username },
      webhookSecretRef: form.webhookSecretRef || undefined,
    });
    setForm(EMPTY_FORM);
    setShowForm(false);
  }

  return (
    <>
      <div className="pagehead">
        <div>
          <h1>ERP connections</h1>
          <p>Each connection is one ERP instance. Credentials are stored encrypted and never shown after saving.</p>
        </div>
        <div className="actions">
          <button className="erp-btn erp-btn--primary" type="button" onClick={() => setShowForm((v) => !v)}>
            {showForm ? "Cancel" : "Add connection"}
          </button>
        </div>
      </div>
      {showForm && (
        <form className="panel stack" onSubmit={handleSubmit}>
          <div className="grid2">
            <div className="field">
              <label htmlFor="erpType">ERP type</label>
              <select className="input" id="erpType" value={form.erpType} onChange={(e) => setForm({ ...form, erpType: e.target.value })}>
                <option value="odoo">Odoo</option>
              </select>
            </div>
            <div className="field">
              <label htmlFor="label">Label</label>
              <input className="input" id="label" value={form.instanceLabel} onChange={(e) => setForm({ ...form, instanceLabel: e.target.value })} required />
            </div>
            <div className="field">
              <label htmlFor="baseUrl">Base URL</label>
              <input className="input" id="baseUrl" value={form.baseUrl} onChange={(e) => setForm({ ...form, baseUrl: e.target.value })} required />
            </div>
            <div className="field">
              <label htmlFor="database">Database</label>
              <input className="input" id="database" value={form.database} onChange={(e) => setForm({ ...form, database: e.target.value })} required />
            </div>
            <div className="field">
              <label htmlFor="username">Username</label>
              <input className="input" id="username" value={form.username} onChange={(e) => setForm({ ...form, username: e.target.value })} required />
            </div>
            <div className="field">
              <label htmlFor="secretRef">
                Secret reference <InfoTag text="A Secrets Manager reference to the ERP login credential — never the raw credential itself." />
              </label>
              <input className="input" id="secretRef" value={form.secretRef} onChange={(e) => setForm({ ...form, secretRef: e.target.value })} required />
            </div>
            <div className="field">
              <label htmlFor="webhookSecretRef">
                Webhook secret reference (optional){" "}
                <InfoTag text="Separate from the login credential — this is what the ERP uses to prove an inbound webhook call came from it." />
              </label>
              <input
                className="input"
                id="webhookSecretRef"
                value={form.webhookSecretRef}
                onChange={(e) => setForm({ ...form, webhookSecretRef: e.target.value })}
              />
            </div>
          </div>
          {registerConnection.error && <div className="callout callout--danger">{(registerConnection.error as Error).message}</div>}
          <div className="actions">
            <button className="erp-btn erp-btn--primary" type="submit" disabled={registerConnection.isPending}>
              {registerConnection.isPending ? "Saving…" : "Save connection"}
            </button>
          </div>
        </form>
      )}
      {error && <div className="callout callout--danger">Could not load connections: {error.message}</div>}
      <DataTable columns={columns} rows={connections ?? []} rowKey={(c) => c.connectionId} isLoading={isLoading} emptyMessage="No connections yet" />
    </>
  );
}
