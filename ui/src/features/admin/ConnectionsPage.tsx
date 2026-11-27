import { useState, type FormEvent } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { Check, Pause, Pencil, Play, Plug, Plus, Search, X, Zap } from "lucide-react";

import { DataTable, type Column } from "../../components/DataTable";
import { IconButton } from "../../components/IconButton";
import { Drawer } from "../../components/Drawer";
import { InfoTag } from "../../components/InfoTag";
import { PageHeader } from "../../components/PageHeader";
import { StatusBadge } from "../../components/StatusBadge";
import {
  useConnections,
  useErpTypes,
  usePauseConnection,
  useRegisterConnection,
  useResumeConnection,
  useTestErpEndpoint,
  useUpdateConnection,
} from "../../hooks/useAdmin";
import type { Connection, ErpField, ErpType } from "../../api/queries/admin";
import type { AuthType, ProbeSample } from "../../api/queries/mapping";
import { ERP_BRANDS } from "../auth/brandIcons";

// What the right-hand panel is doing right now. Only one form is open at a time.
type Mode =
  | { kind: "choose" }
  | { kind: "add"; erp: ErpType }
  | { kind: "edit"; erp: ErpType; connection: Connection }
  | { kind: "custom" }
  | null;
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

/** The brand mark for an ERP, found by name. Unknown ERPs get a plain plug icon. */
function brandMark(name: string) {
  const brand = ERP_BRANDS.find((b) => b.name.toLowerCase() === name.toLowerCase());
  return brand?.svg ? <span className="connection-card__mark" dangerouslySetInnerHTML={{ __html: brand.svg }} /> : null;
}

/** Splits the form's values into the shapes the save mutations take, using the catalog's
 *  `target` for each field — nothing here knows which ERP it is. */
function payloadFor(erp: ErpType, values: Record<string, string>) {
  const field = (target: ErpField["target"]) => erp.fields.find((f) => f.target === target);
  const label = field("LABEL");
  const url = field("BASE_URL");
  const secret = field("SECRET");
  const credentials: Record<string, string> = {};
  for (const f of erp.fields.filter((f) => f.target === "CREDENTIAL")) credentials[f.key] = values[f.key] ?? "";
  return {
    instanceLabel: label ? values[label.key] ?? "" : "",
    baseUrl: url ? values[url.key] ?? "" : "",
    credentials,
    secret: secret && values[secret.key] ? values[secret.key] : null,
  };
}

/** One form for every catalog ERP. Add asks for everything; edit leaves the secret blank
 *  to keep the stored one. */
function ErpForm({
  erp,
  initial,
  editing,
  pending,
  error,
  onCancel,
  onSubmit,
}: {
  erp: ErpType;
  initial: Record<string, string>;
  editing: boolean;
  pending: boolean;
  error: string | null;
  onCancel: () => void;
  onSubmit: (values: Record<string, string>) => void;
}) {
  const [values, setValues] = useState<Record<string, string>>(initial);
  const prefix = `erp-${erp.code.toLowerCase()}`;

  function handleSubmit(e: FormEvent) {
    e.preventDefault();
    onSubmit(values);
  }

  return (
    <form className="stack" onSubmit={handleSubmit}>
      <div className="grid2">
        {erp.fields.map((f) => {
          const id = `${prefix}-${f.key}`;
          const required = !(editing && f.secret);
          return (
            <div className="field" key={f.key}>
              <label htmlFor={id}>
                {f.label} {f.hint && <InfoTag text={f.hint} />}
              </label>
              <input
                className="input"
                id={id}
                type={f.secret ? "password" : f.key === "base_url" ? "url" : "text"}
                placeholder={editing && f.secret ? "Leave blank to keep the current one" : undefined}
                value={values[f.key] ?? ""}
                onChange={(e) => setValues({ ...values, [f.key]: e.target.value })}
                required={required}
              />
            </div>
          );
        })}
      </div>
      {error && <div className="callout callout--danger">{error}</div>}
      <div className="actions">
        <button className="erp-btn erp-btn--primary" type="submit" disabled={pending}>
          {pending ? "Saving…" : editing ? "Save changes" : "Save connection"}
        </button>
        <button className="erp-btn erp-btn--ghost" type="button" onClick={onCancel}>
          Cancel
        </button>
      </div>
    </form>
  );
}

export function ConnectionsPage() {
  const { data: connections, isLoading, error } = useConnections();
  const { data: erpTypes = [] } = useErpTypes();
  const registerConnection = useRegisterConnection();
  const updateConnection = useUpdateConnection();
  const pauseConnection = usePauseConnection();
  const resumeConnection = useResumeConnection();
  const testEndpoint = useTestErpEndpoint();
  const [searchParams] = useSearchParams();

  // Arriving from the Mapping page's "nothing to map yet" empty state opens the Other form
  // directly — the operator came here to do exactly one thing, not to choose again.
  const [mode, setMode] = useState<Mode>(searchParams.get("add") === "custom" ? { kind: "custom" } : null);
  // Shown once, right after a save, so the operator knows what to do next without
  // guessing — a connection with no adapter is only useful once it's also mapped.
  const [justRegistered, setJustRegistered] = useState<{ label: string; mappingStatus: string } | null>(null);
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
    .filter((c) => {
      if (status === "all") return true;
      if (status === "needs-mapping") return c.mappingStatus === "NEEDS_MAPPING";
      return c.status === status;
    })
    .filter((c) => [c.connectionId, c.instanceLabel, c.erpType].join(" ").toLowerCase().includes(search.toLowerCase()));

  function erpSpecFor(erpType: string): ErpType | undefined {
    return erpTypes.find((e) => e.code === erpType);
  }

  /** The form to edit a connection with. A catalog ERP uses its catalog fields. An "Other"
   *  connection has no catalog entry, so its form is built from what was saved for it. */
  function editSpecFor(c: Connection): ErpType {
    const known = erpSpecFor(c.erpType);
    if (known) return known;
    const fields: ErpField[] = [
      { key: "instance_label", label: "Name", hint: "", target: "LABEL", secret: false },
      { key: "base_url", label: "Web address", hint: "", target: "BASE_URL", secret: false },
      ...Object.keys(c.credentials).map((key) => ({ key, label: key, hint: "", target: "CREDENTIAL" as const, secret: false })),
    ];
    if (c.authType !== "NONE") {
      fields.push({
        key: "secret",
        label: AUTH_SECRET_LABEL[c.authType as AuthType] || "Secret",
        hint: "Stored encrypted; leave blank when editing to keep the current one",
        target: "SECRET",
        secret: true,
      });
    }
    return { code: c.erpType, name: c.erpType, authType: c.authType, fields };
  }

  function closeForm() {
    setMode(null);
    setCustomForm(EMPTY_CUSTOM);
    setAuthType("NONE");
    setAuthHeaderName("");
    setAuthUsername("");
    setAuthSecret("");
  }

  async function saveCatalogForm(values: Record<string, string>) {
    if (!mode || (mode.kind !== "add" && mode.kind !== "edit")) return;
    const payload = payloadFor(mode.erp, values);
    if (mode.kind === "add") {
      const result = await registerConnection.mutateAsync({
        erpType: mode.erp.code,
        instanceLabel: payload.instanceLabel,
        baseUrl: payload.baseUrl,
        credentials: payload.credentials,
        auth: { authType: mode.erp.authType as AuthType, params: {}, secret: payload.secret },
      });
      setJustRegistered({ label: payload.instanceLabel, mappingStatus: result.mappingStatus });
    } else {
      await updateConnection.mutateAsync({
        connectionId: mode.connection.connectionId,
        instanceLabel: payload.instanceLabel,
        baseUrl: payload.baseUrl,
        credentials: payload.credentials,
        secret: payload.secret,
      });
    }
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
            {brandMark(c.erpType) ?? <Plug size={16} strokeWidth={1.75} />}
            <span className="connection-card__label">{c.instanceLabel}</span>
          </span>
          <span className="muted mono" style={{ fontSize: 12 }}>{c.baseUrl}</span>
        </div>
      ),
    },
    {
      key: "erp",
      header: "ERP",
      sortValue: (c) => c.erpType,
      render: (c) => <span className="id">{erpSpecFor(c.erpType)?.name ?? c.erpType}</span>,
    },
    {
      key: "status",
      header: "Status",
      sortValue: (c) => c.status,
      render: (c) => (
        <StatusBadge status={c.status === "ACTIVE" ? "Active" : "Paused"} />
      ),
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
                <IconButton icon={Zap} label="Test connection" disabled={testingId === c.connectionId} onClick={() => void runTest(c.connectionId)} />
                <IconButton icon={Pencil} label="Edit connection" onClick={() => setMode({ kind: "edit", erp: editSpecFor(c), connection: c })} />
              {
                (c.status === "ACTIVE" ? (
                  <IconButton icon={Pause} label="Pause connection" onClick={() => pauseConnection.mutate({ connectionId: c.connectionId })} />
                ) : (
                  <IconButton icon={Play} label="Resume connection" onClick={() => resumeConnection.mutate({ connectionId: c.connectionId })} />
                ))}
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

  const saving = registerConnection.isPending || updateConnection.isPending;
  const saveError = (registerConnection.error ?? updateConnection.error) as Error | null;

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
          <button
            className="erp-btn erp-btn--primary"
            type="button"
            style={{ marginLeft: "auto" }}
            onClick={() => setMode({ kind: "choose" })}
          >
            <Plus size={14} aria-hidden="true" /> Add connection
          </button>
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
      <Drawer
        open={mode !== null}
        onClose={closeForm}
        title={
          mode?.kind === "edit"
            ? `Edit ${mode.connection.instanceLabel}`
            : mode?.kind === "add"
              ? `Add ${mode.erp.name}`
              : mode?.kind === "custom"
                ? "Add an ERP that isn't listed"
                : "Add connection"
        }
      >
        {mode?.kind === "choose" && (
          <div className="stack">
            <div className="field">
              <label htmlFor="erpChoice">Which ERP?</label>
              <select
                className="input"
                id="erpChoice"
                defaultValue=""
                onChange={(e) => {
                  const code = e.target.value;
                  if (code === "other") setMode({ kind: "custom" });
                  else {
                    const erp = erpTypes.find((t) => t.code === code);
                    if (erp) setMode({ kind: "add", erp });
                  }
                }}
              >
                <option value="" disabled>
                  Choose…
                </option>
                {erpTypes.map((erp) => (
                  <option key={erp.code} value={erp.code}>
                    {erp.name}
                  </option>
                ))}
                <option value="other">Other (not listed)</option>
              </select>
            </div>
            <div className="actions">
              <button className="erp-btn erp-btn--ghost" type="button" onClick={closeForm}>
                Cancel
              </button>
            </div>
          </div>
        )}

        {(mode?.kind === "add" || mode?.kind === "edit") && (
          <ErpForm
            // A new key per open form, so switching between ERPs or connections resets the inputs.
            key={mode.kind === "edit" ? `edit-${mode.connection.connectionId}` : `add-${mode.erp.code}`}
            erp={mode.erp}
            editing={mode.kind === "edit"}
            initial={
              mode.kind === "edit"
                ? {
                    instance_label: mode.connection.instanceLabel,
                    base_url: mode.connection.baseUrl,
                    ...mode.connection.credentials,
                  }
                : {}
            }
            pending={saving}
            error={saveError ? saveError.message : null}
            onCancel={closeForm}
            onSubmit={(values) => void saveCatalogForm(values)}
          />
        )}

        {mode?.kind === "custom" && (
          <form className="stack" onSubmit={submitCustom}>
            <p className="hint">
              For an ERP that isn't listed. Once you save this, head to <b>ERP mapping</b> to match its fields —
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
              <button className="erp-btn erp-btn--ghost" type="button" onClick={closeForm}>
                Cancel
              </button>
            </div>
          </form>
        )}
        {mode === null && erpTypes.length === 0 && <p className="hint">Loading the list of ERPs…</p>}
      </Drawer>

    </>
  );
}
