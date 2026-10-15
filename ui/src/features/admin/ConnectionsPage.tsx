import { useState, type FormEvent } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { Check, Plug, Plus, Search, X } from "lucide-react";

import { DataTable, type Column } from "../../components/DataTable";
import { InfoTag } from "../../components/InfoTag";
import { PageHeader } from "../../components/PageHeader";
import { StatusBadge } from "../../components/StatusBadge";
import {
  useConnections,
  usePauseConnection,
  useRegisterConnection,
  useResumeConnection,
  useTestErpEndpoint,
} from "../../hooks/useAdmin";
import type { Connection } from "../../api/queries/admin";
import type { AuthType, ProbeSample } from "../../api/queries/mapping";
import { ERP_BRANDS } from "../auth/brandIcons";

type Adding = "odoo" | "custom" | null;
type StatusFilter = "all" | "ACTIVE" | "PAUSED" | "needs-mapping";

const AUTH_TYPE_OPTIONS: { value: AuthType; label: string }[] = [
  { value: "NONE", label: "None" },
  { value: "API_KEY_HEADER", label: "API key (header)" },
  { value: "BASIC", label: "Basic (username + password)" },
  { value: "BEARER_TOKEN", label: "Bearer token" },
];
const AUTH_SECRET_LABEL: Record<AuthType, string> = {
  NONE: "",
  API_KEY_HEADER: "API key",
  BASIC: "Password",
  BEARER_TOKEN: "Token",
};

const EMPTY_ODOO = { instanceLabel: "", baseUrl: "", database: "", username: "", password: "" };
const EMPTY_CUSTOM = { erpType: "", instanceLabel: "", baseUrl: "" };

// ADR-0022: the Mapping page is only ever actionable for NEEDS_MAPPING — the other three
// states are all "nothing to do there right now," just for different reasons, so the badge
// must say which one instead of collapsing them into a single "needs mapping" warning.
const MAPPING_STATUS_LABEL: Record<string, string> = {
  ADAPTER_READY: "Adapter ready",
  NEEDS_MAPPING: "Needs mapping",
  MAPPING_IN_PROGRESS: "Mapping in progress",
  AWAITING_ADAPTER: "Mapping approved — awaiting adapter",
};
const MAPPING_STATUS_TONE: Record<string, "success" | "warning" | "neutral"> = {
  ADAPTER_READY: "success",
  NEEDS_MAPPING: "warning",
  MAPPING_IN_PROGRESS: "neutral",
  AWAITING_ADAPTER: "neutral",
};

function odooIcon() {
  const odoo = ERP_BRANDS.find((b) => b.name === "Odoo");
  return odoo?.svg ? <span className="connection-card__mark" dangerouslySetInnerHTML={{ __html: odoo.svg }} /> : null;
}

export function ConnectionsPage() {
  const { data: connections, isLoading, error } = useConnections();
  const registerConnection = useRegisterConnection();
  const pauseConnection = usePauseConnection();
  const resumeConnection = useResumeConnection();
  const testEndpoint = useTestErpEndpoint();
  const [searchParams] = useSearchParams();

  // Arriving from the Mapping page's "nothing to map yet" empty state opens the New ERP
  // form directly — the operator came here to do exactly one thing, not to choose again.
  const [adding, setAdding] = useState<Adding>(searchParams.get("add") === "custom" ? "custom" : null);
  // Shown once, right after a save, so the operator knows what to do next without
  // guessing — a connection with no adapter is only useful once it's also mapped.
  const [justRegistered, setJustRegistered] = useState<{ label: string; mappingStatus: string } | null>(null);
  const [odooForm, setOdooForm] = useState(EMPTY_ODOO);
  const [customForm, setCustomForm] = useState(EMPTY_CUSTOM);
  const [authType, setAuthType] = useState<AuthType>("NONE");
  const [authHeaderName, setAuthHeaderName] = useState("");
  const [authUsername, setAuthUsername] = useState("");
  const [authSecret, setAuthSecret] = useState("");
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState<StatusFilter>("all");
  // Per-row test outcome, keyed by connection id — the result shows inline on the row
  // that was tested, not in a toast, so it stays readable while trying a few in a row.
  const [testResults, setTestResults] = useState<Record<string, ProbeSample>>({});
  const [testingId, setTestingId] = useState<string | null>(null);

  const all = connections ?? [];
  const counts = {
    all: all.length,
    ACTIVE: all.filter((c) => c.status === "ACTIVE").length,
    PAUSED: all.filter((c) => c.status === "PAUSED").length,
    needsMapping: all.filter((c) => c.mappingStatus === "NEEDS_MAPPING").length,
  };

  const rows = all
    .filter((c) =>
      status === "all"
        ? true
        : status === "needs-mapping"
          ? c.mappingStatus === "NEEDS_MAPPING"
          : c.status === status,
    )
    .filter((c) => [c.connectionId, c.instanceLabel, c.erpType].join(" ").toLowerCase().includes(search.toLowerCase()));

  function closeForm() {
    setAdding(null);
    setOdooForm(EMPTY_ODOO);
    setCustomForm(EMPTY_CUSTOM);
    setAuthType("NONE");
    setAuthHeaderName("");
    setAuthUsername("");
    setAuthSecret("");
  }

  async function submitOdoo(e: FormEvent) {
    e.preventDefault();
    const result = await registerConnection.mutateAsync({
      erpType: "ODOO",
      instanceLabel: odooForm.instanceLabel,
      baseUrl: odooForm.baseUrl,
      credentials: { database: odooForm.database, username: odooForm.username },
      auth: { authType: "BASIC", params: {}, secret: odooForm.password },
    });
    setJustRegistered({ label: odooForm.instanceLabel, mappingStatus: result.mappingStatus });
    closeForm();
  }

  async function submitCustom(e: FormEvent) {
    e.preventDefault();
    const params: Record<string, string> =
      authType === "API_KEY_HEADER" ? { header_name: authHeaderName.trim() || "X-API-Key" }
      : authType === "BASIC" ? { username: authUsername.trim() }
      : {};
    const result = await registerConnection.mutateAsync({
      erpType: customForm.erpType,
      instanceLabel: customForm.instanceLabel,
      baseUrl: customForm.baseUrl,
      credentials: {},
      auth: { authType, params, secret: authType === "NONE" ? null : authSecret },
    });
    setJustRegistered({ label: customForm.instanceLabel, mappingStatus: result.mappingStatus });
    closeForm();
  }

  async function runTest(connectionId: string) {
    setTestingId(connectionId);
    try {
      const sample = await testEndpoint.mutateAsync({ connectionId, path: "" });
      setTestResults((prev) => ({ ...prev, [connectionId]: sample }));
    } finally {
      setTestingId(null);
    }
  }

  const columns: Column<Connection>[] = [
    {
      key: "label",
      header: "Connection",
      sortValue: (c) => c.instanceLabel,
      render: (c) => (
        <div className="cell-stack">
          <span className="connection-card__head">
            {c.erpType === "ODOO" ? odooIcon() : <Plug size={16} strokeWidth={1.75} />}
            <span className="connection-card__label">{c.instanceLabel}</span>
          </span>
          <span className="muted mono" style={{ fontSize: 12 }}>{c.baseUrl}</span>
        </div>
      ),
    },
    { key: "erp", header: "ERP", sortValue: (c) => c.erpType, render: (c) => <span className="id">{c.erpType}</span> },
    {
      key: "status",
      header: "Status",
      sortValue: (c) => c.status,
      render: (c) => <StatusBadge status={c.status === "ACTIVE" ? "Active" : "Paused"} />,
    },
    {
      key: "adapter",
      header: "Adapter",
      sortValue: (c) => (c.hasAdapter ? 1 : 0),
      render: (c) => (
        <span className={`erp-badge erp-badge--${MAPPING_STATUS_TONE[c.mappingStatus] ?? "neutral"}`}>
          {MAPPING_STATUS_LABEL[c.mappingStatus] ?? c.mappingStatus}
        </span>
      ),
    },
    {
      key: "actions",
      header: "",
      render: (c) => {
        const result = testResults[c.connectionId];
        return (
          <div className="cell-stack">
            <div className="actions">
              <button
                className="erp-btn erp-btn--ghost erp-btn--sm"
                type="button"
                disabled={testingId === c.connectionId}
                onClick={(e) => {
                  e.stopPropagation();
                  void runTest(c.connectionId);
                }}
              >
                {testingId === c.connectionId ? "Testing…" : "Test"}
              </button>
              {c.status === "ACTIVE" ? (
                <button
                  className="erp-btn erp-btn--ghost erp-btn--sm"
                  type="button"
                  onClick={(e) => {
                    e.stopPropagation();
                    pauseConnection.mutate({ connectionId: c.connectionId });
                  }}
                >
                  Pause
                </button>
              ) : (
                <button
                  className="erp-btn erp-btn--ghost erp-btn--sm"
                  type="button"
                  onClick={(e) => {
                    e.stopPropagation();
                    resumeConnection.mutate({ connectionId: c.connectionId });
                  }}
                >
                  Resume
                </button>
              )}
            </div>
            {result && (
              <span className={`test-result test-result--${result.error ? "danger" : "success"}`}>
                {result.error ? <X size={13} strokeWidth={2.5} /> : <Check size={13} strokeWidth={2.5} />}
                {result.error ?? "Reachable"}
              </span>
            )}
          </div>
        );
      },
    },
  ];

  const TILES: { value: StatusFilter; label: string; count: number; dot: string }[] = [
    { value: "all", label: "All connections", count: counts.all, dot: "neutral" },
    { value: "ACTIVE", label: "Active", count: counts.ACTIVE, dot: "success" },
    { value: "PAUSED", label: "Paused", count: counts.PAUSED, dot: "neutral" },
    { value: "needs-mapping", label: "Needs mapping", count: counts.needsMapping, dot: "warning" },
  ];

  return (
    <>
      <PageHeader
        title="ERP connections"
        subtitle="Every ERP instance, known or brand new, lives here — credentials are stored encrypted and never shown again after saving."
      />

      {justRegistered && justRegistered.mappingStatus === "NEEDS_MAPPING" && (
        <div className="callout callout--info">
          <span>
            <b>{justRegistered.label}</b> is saved, but has no adapter yet — it won't deliver orders until one
            exists. Next: match its fields on the ERP mapping page.
          </span>
          <Link className="erp-btn erp-btn--secondary erp-btn--sm" to="/admin/mappings">
            Go to ERP mapping
          </Link>
        </div>
      )}
      {justRegistered &&
        (justRegistered.mappingStatus === "MAPPING_IN_PROGRESS" ||
          justRegistered.mappingStatus === "AWAITING_ADAPTER") && (
          <div className="callout callout--info">
            <span>
              <b>{justRegistered.label}</b> is saved. Its ERP type already has a mapping
              {justRegistered.mappingStatus === "AWAITING_ADAPTER"
                ? " approved and waiting for the generated adapter code to land"
                : " in progress"}
              — there's nothing to do on the Mapping page yet.
            </span>
          </div>
        )}

      <section className="panel stack">
        <h2>Add a connection</h2>
        <div className="card-grid">
          <button type="button" className={`pickcard ${adding === "odoo" ? "is-selected" : ""}`} onClick={() => setAdding(adding === "odoo" ? null : "odoo")}>
            {odooIcon()}
            <span className="pickcard__label">Odoo</span>
            <span className="pickcard__meta">Another Odoo instance</span>
          </button>
          <button type="button" className={`pickcard ${adding === "custom" ? "is-selected" : ""}`} onClick={() => setAdding(adding === "custom" ? null : "custom")}>
            <Plus size={18} strokeWidth={1.75} />
            <span className="pickcard__label">New ERP</span>
            <span className="pickcard__meta">Not supported yet — onboard it</span>
          </button>
        </div>

        {adding === "odoo" && (
          <form className="stack" onSubmit={submitOdoo}>
            <div className="grid2">
              <div className="field">
                <label htmlFor="odooLabel">Label</label>
                <input className="input" id="odooLabel" value={odooForm.instanceLabel} onChange={(e) => setOdooForm({ ...odooForm, instanceLabel: e.target.value })} required />
              </div>
              <div className="field">
                <label htmlFor="odooBaseUrl">Base URL</label>
                <input className="input" id="odooBaseUrl" type="url" placeholder="http://odoo.example.com:8069" value={odooForm.baseUrl} onChange={(e) => setOdooForm({ ...odooForm, baseUrl: e.target.value })} required />
              </div>
              <div className="field">
                <label htmlFor="odooDatabase">Database</label>
                <input className="input" id="odooDatabase" value={odooForm.database} onChange={(e) => setOdooForm({ ...odooForm, database: e.target.value })} required />
              </div>
              <div className="field">
                <label htmlFor="odooUsername">Username</label>
                <input className="input" id="odooUsername" value={odooForm.username} onChange={(e) => setOdooForm({ ...odooForm, username: e.target.value })} required />
              </div>
              <div className="field">
                <label htmlFor="odooPassword">Password</label>
                <input className="input" id="odooPassword" type="password" value={odooForm.password} onChange={(e) => setOdooForm({ ...odooForm, password: e.target.value })} required />
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

        {adding === "custom" && (
          <form className="stack" onSubmit={submitCustom}>
            <p className="hint">
              For an ERP with no adapter yet. Once you save this, head to <b>ERP mapping</b> to match its fields —
              that step reads the connection details you enter here, nothing is retyped.
            </p>
            <div className="grid2">
              <div className="field">
                <label htmlFor="customErpType">
                  ERP name <InfoTag text="Used to group every connection of this ERP together — the mapping/adapter work only ever happens once per name." />
                </label>
                <input className="input" id="customErpType" placeholder="e.g. Shopify" value={customForm.erpType} onChange={(e) => setCustomForm({ ...customForm, erpType: e.target.value })} required />
              </div>
              <div className="field">
                <label htmlFor="customLabel">Label</label>
                <input className="input" id="customLabel" value={customForm.instanceLabel} onChange={(e) => setCustomForm({ ...customForm, instanceLabel: e.target.value })} required />
              </div>
              <div className="field">
                <label htmlFor="customBaseUrl">Base URL</label>
                <input className="input" id="customBaseUrl" type="url" placeholder="https://erp.example.com/api" value={customForm.baseUrl} onChange={(e) => setCustomForm({ ...customForm, baseUrl: e.target.value })} required />
              </div>
              <div className="field">
                <label htmlFor="customAuthType">Authentication</label>
                <select className="input" id="customAuthType" value={authType} onChange={(e) => setAuthType(e.target.value as AuthType)}>
                  {AUTH_TYPE_OPTIONS.map((o) => (
                    <option key={o.value} value={o.value}>
                      {o.label}
                    </option>
                  ))}
                </select>
              </div>
            </div>
            {authType === "API_KEY_HEADER" && (
              <div className="grid2">
                <div className="field">
                  <label htmlFor="customHeaderName">Header name</label>
                  <input className="input" id="customHeaderName" placeholder="X-API-Key" value={authHeaderName} onChange={(e) => setAuthHeaderName(e.target.value)} />
                </div>
                <div className="field">
                  <label htmlFor="customSecret">{AUTH_SECRET_LABEL[authType]}</label>
                  <input className="input" id="customSecret" type="password" value={authSecret} onChange={(e) => setAuthSecret(e.target.value)} required />
                </div>
              </div>
            )}
            {authType === "BASIC" && (
              <div className="grid2">
                <div className="field">
                  <label htmlFor="customUsername">Username</label>
                  <input className="input" id="customUsername" value={authUsername} onChange={(e) => setAuthUsername(e.target.value)} />
                </div>
                <div className="field">
                  <label htmlFor="customSecret">{AUTH_SECRET_LABEL[authType]}</label>
                  <input className="input" id="customSecret" type="password" value={authSecret} onChange={(e) => setAuthSecret(e.target.value)} required />
                </div>
              </div>
            )}
            {authType === "BEARER_TOKEN" && (
              <div className="field">
                <label htmlFor="customSecret">{AUTH_SECRET_LABEL[authType]}</label>
                <input className="input" id="customSecret" type="password" value={authSecret} onChange={(e) => setAuthSecret(e.target.value)} required />
              </div>
            )}
            {registerConnection.error && <div className="callout callout--danger">{(registerConnection.error as Error).message}</div>}
            <div className="actions">
              <button className="erp-btn erp-btn--primary" type="submit" disabled={registerConnection.isPending}>
                {registerConnection.isPending ? "Saving…" : "Save connection"}
              </button>
            </div>
          </form>
        )}
      </section>

      <section className="panel stack">
        <h2>Connections</h2>
        <div className="filtertiles">
          {TILES.map((t) => (
            <button
              key={t.value}
              type="button"
              className="filtertile"
              aria-pressed={status === t.value}
              onClick={() => setStatus(t.value)}
            >
              <b>{t.count}</b>
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
              placeholder="Search by connection, label, or ERP"
              style={{ width: 280 }}
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
          </div>
        </div>
        {error && <div className="callout callout--danger">Could not load connections: {error.message}</div>}
        <DataTable
          columns={columns}
          rows={rows}
          rowKey={(c) => c.connectionId}
          isLoading={isLoading}
          emptyMessage="No connections match this filter."
          pageSize={10}
        />
      </section>
    </>
  );
}
