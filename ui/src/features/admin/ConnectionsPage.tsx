import { useState, type FormEvent } from "react";
import { Search } from "lucide-react";

import { DataTable, type Column } from "../../components/DataTable";
import { FilterMenu } from "../../components/FilterMenu";
import { InfoTag } from "../../components/InfoTag";
import { PageHeader } from "../../components/PageHeader";
import { StatusBadge } from "../../components/StatusBadge";
import { useConnections, usePauseConnection, useRegisterConnection, useResumeConnection } from "../../hooks/useAdmin";
import type { Connection } from "../../api/queries/admin";

const EMPTY_FORM = { erpType: "odoo", instanceLabel: "", baseUrl: "", database: "", username: "", secretRef: "", webhookSecretRef: "" };
const STATUS_FILTERS = ["all", "ACTIVE", "PAUSED"] as const;
const STATUS_OPTIONS = STATUS_FILTERS.map((s) => ({ value: s, label: s === "all" ? "All" : s === "ACTIVE" ? "Active" : "Paused" }));

export function ConnectionsPage() {
  const { data: connections, isLoading, error } = useConnections();
  const registerConnection = useRegisterConnection();
  const pauseConnection = usePauseConnection();
  const resumeConnection = useResumeConnection();
  const [form, setForm] = useState(EMPTY_FORM);
  const [showForm, setShowForm] = useState(false);
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState<(typeof STATUS_FILTERS)[number]>("all");

  const rows = (connections ?? [])
    .filter((c) => status === "all" || c.status === status)
    .filter((c) => [c.connectionId, c.instanceLabel, c.erpType].join(" ").toLowerCase().includes(search.toLowerCase()));

  const columns: Column<Connection>[] = [
    { key: "id", header: "Connection", render: (c) => <span className="id">{c.connectionId}</span>, sortValue: (c) => c.connectionId },
    { key: "label", header: "Label", render: (c) => c.instanceLabel, sortValue: (c) => c.instanceLabel },
    { key: "erp", header: "ERP", render: (c) => c.erpType, sortValue: (c) => c.erpType },
    { key: "status", header: "Status", render: (c) => <StatusBadge status={c.status} />, sortValue: (c) => c.status },
    {
      key: "webhook",
      header: "Webhook secret",
      render: (c) => (c.hasWebhookSecret ? "Configured" : "Not set"),
      sortValue: (c) => (c.hasWebhookSecret ? 1 : 0),
    },
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
      <PageHeader
        title="ERP connections"
        subtitle="Each connection is one ERP instance. Credentials are stored encrypted and never shown after saving."
        actions={
          <button className="erp-btn erp-btn--primary" type="button" onClick={() => setShowForm((v) => !v)}>
            {showForm ? "Cancel" : "Add connection"}
          </button>
        }
      />
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
      <div className="toolbar">
        <div className="search-input">
          <Search size={15} strokeWidth={2} className="search-input__icon" />
          <input
            className="input"
            type="search"
            placeholder="Search by connection, label, or ERP"
            style={{ width: 280 }}
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>
        <FilterMenu groups={[{ label: "Status", options: STATUS_OPTIONS, value: status, onChange: (v) => setStatus(v as (typeof STATUS_FILTERS)[number]) }]} />
      </div>
      {error && <div className="callout callout--danger">Could not load connections: {error.message}</div>}
      <DataTable columns={columns} rows={rows} rowKey={(c) => c.connectionId} isLoading={isLoading} emptyMessage="No connections match this filter" pageSize={10} />
    </>
  );
}
