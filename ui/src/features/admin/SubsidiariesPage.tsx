import { useState, type FormEvent } from "react";

import { DataTable, type Column } from "../../components/DataTable";
import { InfoTag } from "../../components/InfoTag";
import {
  useConnections,
  useCreateSubsidiary,
  useErpRoute,
  useSubsidiaries,
  useSetErpRoute,
} from "../../hooks/useAdmin";
import type { Connection, Subsidiary } from "../../api/queries/admin";

function ColumnHeader({ label, help }: { label: string; help: string }) {
  return (
    <>
      {label}
      <InfoTag text={help} />
    </>
  );
}

function ConnectionCell({ subsidiary, connections }: { subsidiary: Subsidiary; connections: Connection[] }) {
  const { data: route, isLoading } = useErpRoute(subsidiary.subsidiaryId);
  const setRoute = useSetErpRoute();
  const [connectionDraft, setConnectionDraft] = useState<string | null>(null);
  const connectionId = connectionDraft ?? route?.connectionId ?? "";
  const companyId = route?.erpCompanyId ?? "";

  if (isLoading) return <span className="muted">Loading…</span>;

  async function save(nextConnection: string, nextCompany: string) {
    if (!nextConnection) return;
    await setRoute.mutateAsync({
      subsidiaryId: subsidiary.subsidiaryId,
      connectionId: nextConnection,
      erpCompanyId: nextCompany.trim(),
    });
  }

  return (
    <select
      className="input"
      aria-label="ERP connection"
      value={connectionId}
      onChange={(e) => {
        const next = e.target.value;
        if (!next) return;
        setConnectionDraft(next);
        void save(next, companyId);
      }}
      disabled={setRoute.isPending}
    >
      <option value="">Not chosen yet</option>
      {connections.map((c) => (
        <option key={c.connectionId} value={c.connectionId}>
          {c.instanceLabel}
        </option>
      ))}
    </select>
  );
}

function CompanyNumberCell({ subsidiary }: { subsidiary: Subsidiary }) {
  const { data: route, isLoading } = useErpRoute(subsidiary.subsidiaryId);
  const setRoute = useSetErpRoute();
  const [companyDraft, setCompanyDraft] = useState<string | null>(null);
  const connectionId = route?.connectionId ?? "";
  const companyId = companyDraft ?? route?.erpCompanyId ?? "";

  if (isLoading) return <span className="muted">Loading…</span>;

  return (
    <input
      className="input"
      value={companyId}
      placeholder="Company number"
      aria-label="ERP company number"
      onChange={(e) => setCompanyDraft(e.target.value)}
      onBlur={() => {
        if (!connectionId) return;
        void setRoute.mutateAsync({
          subsidiaryId: subsidiary.subsidiaryId,
          connectionId,
          erpCompanyId: companyId.trim(),
        });
      }}
      disabled={setRoute.isPending || !connectionId}
    />
  );
}

export function SubsidiariesPage() {
  const { data: subsidiaries, isLoading, error } = useSubsidiaries();
  const { data: connections } = useConnections();
  const createSubsidiary = useCreateSubsidiary();
  const EMPTY = { name: "", country: "", language: "" };
  const [form, setForm] = useState(EMPTY);
  const [showForm, setShowForm] = useState(false);

  const columns: Column<Subsidiary>[] = [
    {
      key: "id",
      header: <ColumnHeader label="Id" help="Our id for this distributor company, such as sub_demo. This is not a number from the ERP." />,
      render: (c) => <span className="id">{c.subsidiaryId}</span>,
    },
    {
      key: "name",
      header: <ColumnHeader label="Name" help="The name shown in AdminOps, such as Demo subsidiary." />,
      render: (c) => c.name,
    },
    {
      key: "country",
      header: <ColumnHeader label="Country" help="Two-letter country code we store, such as US. It is not read from the ERP and does not decide which orders are kept." />,
      render: (c) => c.country,
    },
    {
      key: "language",
      header: <ColumnHeader label="Language" help="Language code we store, such as en_US. It is not read from the ERP and does not decide which orders are kept." />,
      render: (c) => c.language,
    },
    {
      key: "connection",
      header: (
        <ColumnHeader
          label="ERP connection"
          help="Add the login first on ERP connections, then select it here. One connection belongs to one subsidiary."
        />
      ),
      render: (c) => <ConnectionCell subsidiary={c} connections={connections ?? []} />,
    },
    {
      key: "company",
      header: (
        <ColumnHeader
          label="ERP company number"
          help="The company id inside that ERP. On the demo row, 1 is YourCompany. A sales order is kept only when the quotation’s company id is this number."
        />
      ),
      render: (c) => <CompanyNumberCell subsidiary={c} />,
    },
  ];

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    await createSubsidiary.mutateAsync(form);
    setForm(EMPTY);
    setShowForm(false);
  }

  return (
    <>
      <div className="pagehead">
        <div>
          <h1>Subsidiaries</h1>
          <p>
            Each row is one distributor company. Add the login on ERP connections first, then select it in ERP connection. The number in ERP company number is the company id inside that ERP. A sales order is kept only when the quotation uses that same company.
          </p>
        </div>
        <div className="actions">
          <button className="erp-btn erp-btn--primary" type="button" onClick={() => setShowForm((v) => !v)}>
            {showForm ? "Cancel" : "Add subsidiary"}
          </button>
        </div>
      </div>
      {showForm && (
        <form className="panel stack" onSubmit={handleSubmit}>
          <div className="grid2">
            <div className="field">
              <label htmlFor="sub-name">Name <InfoTag text="What you will call this distributor company in AdminOps." /></label>
              <input className="input" id="sub-name" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} required />
            </div>
            <div className="field">
              <label htmlFor="sub-country">Country <InfoTag text="Two-letter country code, such as US. Stored here only. The ERP does not use it." /></label>
              <input className="input" id="sub-country" value={form.country} onChange={(e) => setForm({ ...form, country: e.target.value.toUpperCase() })} maxLength={2} placeholder="e.g. DE" required />
            </div>
            <div className="field">
              <label htmlFor="sub-language">Language <InfoTag text="Language code, such as en_US. Stored here only. The ERP does not use it." /></label>
              <input className="input" id="sub-language" value={form.language} onChange={(e) => setForm({ ...form, language: e.target.value })} maxLength={5} placeholder="e.g. de" required />
            </div>
          </div>
          {createSubsidiary.error && <div className="callout callout--danger">{(createSubsidiary.error as Error).message}</div>}
          <div className="actions">
            <button className="erp-btn erp-btn--primary" type="submit" disabled={createSubsidiary.isPending}>
              {createSubsidiary.isPending ? "Saving…" : "Save subsidiary"}
            </button>
          </div>
        </form>
      )}
      {error && <div className="callout callout--danger">Could not load subsidiaries: {error.message}</div>}
      <DataTable columns={columns} rows={subsidiaries ?? []} rowKey={(c) => c.subsidiaryId} emptyMessage={isLoading ? "Loading…" : "No subsidiaries yet"} />
    </>
  );
}
