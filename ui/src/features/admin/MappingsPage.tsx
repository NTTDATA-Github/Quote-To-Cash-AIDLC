import { useEffect, useState, type ChangeEvent, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { Plug, Sparkles } from "lucide-react";

import { DataTable, type Column } from "../../components/DataTable";
import { InfoTag } from "../../components/InfoTag";
import { PageHeader } from "../../components/PageHeader";
import { StatusBadge, type Role } from "../../components/StatusBadge";
import type { MappableConnection, MappingEntry, MappingJob, ProbeSample } from "../../api/queries/mapping";
import {
  useAdapterRun,
  useApproveMapping,
  useCanonicalOrderSchema,
  useCanonicalSchemas,
  useMappableConnections,
  useMappingJobs,
  useProbeErpSamples,
  useRegisterCanonicalSchema,
  useSubmitMapping,
  useSubmitMappingFromProbe,
  useSuggestSampleRequests,
  type SampleFile,
} from "../../hooks/useMapping";

type Source = "live" | "registered" | "oneoff" | "new";
type SampleSource = "files" | "live";
type JobFilter = "all" | "progress" | "DONE" | "FAILED";

interface LiveRequest {
  label: string;
  method: string;
  path: string;
}

// PENDING | PROCESSING | DONE | FAILED -> the generic badge. These are job states, not
// order-lifecycle statuses, so they intentionally render neutral (FAILED -> danger via
// the shared badge table); no new design-system status wording is introduced.
const STATUS_LABEL: Record<string, string> = {
  PENDING: "Pending",
  PROCESSING: "Processing",
  DONE: "Done",
  FAILED: "Failed",
};

function statusLabel(status: string): string {
  return STATUS_LABEL[status] ?? status;
}

// Plain-English read of the 0-100 confidence score, so a non-technical reviewer can
// judge a row from its color/label alone — the number is still shown, just not the
// only thing doing the talking.
function confidenceTier(score: number): { label: string; role: Role } {
  if (score >= 95) return { label: "High confidence", role: "success" };
  if (score >= 80) return { label: "Needs review", role: "warning" };
  return { label: "Low confidence", role: "danger" };
}

function downloadBlob(filename: string, text: string, mime: string): void {
  const url = URL.createObjectURL(new Blob([text], { type: mime }));
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

function toCsv(mapping: MappingEntry[]): string {
  const escape = (value: string | number) => {
    const s = String(value);
    return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  };
  const header = "erp_field,canonical_field,sample_data,confidence";
  const rows = mapping.map((m) =>
    [m.erpField, m.canonicalField, m.sampleData, m.confidence].map(escape).join(","),
  );
  return [header, ...rows].join("\n");
}

interface CanonicalField {
  field: string;
  description: string;
}

// Tolerates the same "field,description" shape canonicalOrderSchema/registered-schema
// CSVs already use, including a literal "field" header row.
function parseCanonicalCsv(csvText: string): CanonicalField[] {
  const lines = csvText.split("\n").map((l) => l.trim()).filter(Boolean);
  return lines
    .filter((l) => l.toLowerCase() !== "field,description")
    .map((line) => {
      const i = line.indexOf(",");
      return i === -1
        ? { field: line, description: "" }
        : { field: line.slice(0, i).trim(), description: line.slice(i + 1).trim() };
    });
}

function canonicalFieldsToCsv(fields: CanonicalField[]): string {
  return ["field,description", ...fields.map((f) => `${f.field},${f.description}`)].join("\n");
}

const STEPS = ["Connect", "Canonical fields", "Review", "Approve"] as const;

function Stepper({ active }: { active: number }) {
  return (
    <ol className="wizard-steps">
      {STEPS.map((label, i) => (
        <li key={label} className={i === active ? "is-active" : i < active ? "is-done" : ""}>
          <span className="wizard-steps__dot">{i < active ? "✓" : i + 1}</span>
          {label}
        </li>
      ))}
    </ol>
  );
}

function ConnectionPicker({
  connections,
  selected,
  onSelect,
}: {
  connections: MappableConnection[];
  selected: string | null;
  onSelect: (connectionId: string) => void;
}) {
  if (connections.length === 0) {
    return (
      <div className="empty-card">
        <Plug size={22} strokeWidth={1.75} />
        <p>Nothing needs mapping right now.</p>
        <p className="hint">
          This step needs a connection for an ERP with no adapter yet. Every connection you have either
          already has one, or already has a mapping in progress — so there's nothing to pick from here.
          To onboard a brand-new ERP: register its base URL and how to authenticate to it on the ERP
          connections page first (the button below opens that form directly) — once saved, it reappears
          here automatically, ready to map.
        </p>
        <Link className="erp-btn erp-btn--secondary erp-btn--sm" to="/admin/connections?add=custom">
          Add a new ERP connection
        </Link>
      </div>
    );
  }
  return (
    <div className="card-grid">
      {connections.map((c) => (
        <button
          key={c.connectionId}
          type="button"
          className={`pickcard ${selected === c.connectionId ? "is-selected" : ""}`}
          onClick={() => onSelect(c.connectionId)}
        >
          <span className="pickcard__icon">
            <Sparkles size={18} strokeWidth={1.75} />
          </span>
          <span className="pickcard__label">{c.instanceLabel}</span>
          <span className="pickcard__meta">{c.erpType}</span>
        </button>
      ))}
    </div>
  );
}

export function MappingsPage() {
  const { data: connections, error: connectionsError } = useMappableConnections();
  const { data: schemas, error: schemasError } = useCanonicalSchemas();
  const { data: liveOrderSchema, isLoading: liveOrderSchemaLoading } = useCanonicalOrderSchema();
  const { data: jobs, error: jobsError, isLoading: jobsLoading } = useMappingJobs();
  const registerSchema = useRegisterCanonicalSchema();
  const submit = useSubmitMapping();
  const submitFromProbe = useSubmitMappingFromProbe();
  const probe = useProbeErpSamples();
  const suggestRequests = useSuggestSampleRequests();
  const approve = useApproveMapping();

  const [connectionId, setConnectionId] = useState<string | null>(null);
  // "live" is the default — it needs no operator action at all, see canonicalOrderSchema.
  const [source, setSource] = useState<Source>("live");
  // Editable copy of the live schema, shown as a table — starts null so the first fetch
  // seeds it; after that, edits here win over a later refetch (don't clobber a row the
  // operator just changed).
  const [liveFields, setLiveFields] = useState<CanonicalField[] | null>(null);
  useEffect(() => {
    if (liveOrderSchema && liveFields === null) setLiveFields(parseCanonicalCsv(liveOrderSchema));
  }, [liveOrderSchema, liveFields]);
  const [selectedSchema, setSelectedSchema] = useState("");
  const [newSchemaName, setNewSchemaName] = useState("");
  const [newSchemaCsv, setNewSchemaCsv] = useState("");
  const [oneoffCsv, setOneoffCsv] = useState("");
  const [sampleSource, setSampleSource] = useState<SampleSource>("files");
  const [sampleFiles, setSampleFiles] = useState<SampleFile[]>([]);
  const [liveRequests, setLiveRequests] = useState<LiveRequest[]>([
    { label: "orders", method: "GET", path: "" },
  ]);
  const [probePreview, setProbePreview] = useState<ProbeSample[] | null>(null);
  const [jobId, setJobId] = useState<string | null>(null);
  const [approved, setApproved] = useState(false);
  const [jobFilter, setJobFilter] = useState<JobFilter>("all");

  const job = (jobs ?? []).find((item) => item.jobId === jobId) ?? null;
  const runEnabled = approved || !!job?.adapterRunId;
  const { data: run } = useAdapterRun(jobId, runEnabled);

  function liveRequestInputs() {
    return liveRequests
      .filter((r) => r.label.trim() && r.path.trim())
      .map((r) => ({ label: r.label.trim(), method: r.method, path: r.path.trim(), queryParams: {} }));
  }

  const canonicalFieldsReady =
    (source === "live" && !!liveFields && liveFields.length > 0) ||
    (source === "registered" && !!selectedSchema) ||
    (source === "oneoff" && !!oneoffCsv.trim());
  const liveReady = liveRequestInputs().length > 0;

  // Same resolution everywhere canonical fields are needed (submit, suggest-requests):
  // exactly one of a registered schema, a pasted/uploaded CSV, or the (possibly
  // operator-edited) live order schema.
  function resolveCanonicalFields(): { schemaName: string | null; canonicalFieldsCsv: string | null } {
    if (source === "registered") return { schemaName: selectedSchema, canonicalFieldsCsv: null };
    if (source === "oneoff") return { schemaName: null, canonicalFieldsCsv: oneoffCsv };
    if (source === "live") {
      return { schemaName: null, canonicalFieldsCsv: liveFields ? canonicalFieldsToCsv(liveFields) : null };
    }
    return { schemaName: null, canonicalFieldsCsv: null };
  }

  function updateLiveField(i: number, patch: Partial<CanonicalField>) {
    setLiveFields((prev) => (prev ?? []).map((f, j) => (j === i ? { ...f, ...patch } : f)));
  }

  const canSubmit =
    !!connectionId &&
    canonicalFieldsReady &&
    (sampleSource === "files" ? sampleFiles.length > 0 : liveReady);

  const activeStep = approved || job?.adapterRunId ? 3 : job ? 2 : connectionId ? 1 : 0;

  async function handleFiles(e: ChangeEvent<HTMLInputElement>) {
    const files = Array.from(e.target.files ?? []);
    const read = await Promise.all(
      files.map(async (f) => ({ filename: f.name, content: await f.text() })),
    );
    setSampleFiles(read);
  }

  async function loadCsv(e: ChangeEvent<HTMLInputElement>, setCsv: (value: string) => void) {
    const file = e.target.files?.[0];
    if (file) setCsv(await file.text());
  }

  // Clicking a job row pins the inspector to that job (by design, so you can go back and
  // inspect past jobs) — this is the way out of that, back to a blank proposal, without
  // a page reload.
  function startNewMapping() {
    setJobId(null);
    setApproved(false);
    setConnectionId(null);
    setSource("live");
    setSelectedSchema("");
    setNewSchemaName("");
    setNewSchemaCsv("");
    setOneoffCsv("");
    setSampleSource("files");
    setSampleFiles([]);
    setLiveRequests([{ label: "orders", method: "GET", path: "" }]);
    setProbePreview(null);
  }

  async function handleRegister() {
    await registerSchema.mutateAsync({ name: newSchemaName.trim(), csvText: newSchemaCsv });
    setSource("registered");
    setSelectedSchema(newSchemaName.trim());
    setNewSchemaName("");
    setNewSchemaCsv("");
  }

  async function handleTestConnection() {
    if (!connectionId) return;
    setProbePreview(null);
    const results = await probe.mutateAsync({ connectionId, requests: liveRequestInputs() });
    setProbePreview(results);
  }

  // Grounds the suggestion in whichever canonical fields were picked above, same
  // resolution as handleSubmit. Then immediately fires the suggested requests too
  // (read-only GETs against a connection the operator already registered) so one click
  // gets both the guess and the data, instead of making them click "Test connection"
  // again right after.
  async function handleSuggestRequests() {
    if (!connectionId || !canonicalFieldsReady) return;
    const { schemaName, canonicalFieldsCsv } = resolveCanonicalFields();
    const suggestions = await suggestRequests.mutateAsync({ connectionId, schemaName, canonicalFieldsCsv });
    if (suggestions.length === 0) return;
    setLiveRequests(suggestions);
    setProbePreview(null);
    const results = await probe.mutateAsync({
      connectionId,
      requests: suggestions.map((r) => ({ label: r.label, method: r.method, path: r.path, queryParams: {} })),
    });
    setProbePreview(results);
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    if (!connectionId) return;
    setApproved(false);
    const { schemaName, canonicalFieldsCsv } = resolveCanonicalFields();
    const result =
      sampleSource === "files"
        ? await submit.mutateAsync({ connectionId, sampleFiles, schemaName, canonicalFieldsCsv })
        : await submitFromProbe.mutateAsync({
            connectionId,
            requests: liveRequestInputs(),
            schemaName,
            canonicalFieldsCsv,
          });
    setJobId(result.jobId);
  }

  const mapping = job?.mapping ?? [];
  // Worst first — the rows that need a human's eyes should be the first thing seen,
  // not something found by scanning past the fields that are already fine.
  const sortedMapping = [...mapping].sort((a, b) => a.confidence - b.confidence);
  const tiers = sortedMapping.map((m) => ({ entry: m, tier: confidenceTier(m.confidence) }));
  const tierCounts = {
    high: tiers.filter((t) => t.tier.role === "success").length,
    review: tiers.filter((t) => t.tier.role === "warning").length,
    low: tiers.filter((t) => t.tier.role === "danger").length,
  };
  const isRunning = !!jobId && (!job || job.status === "PENDING" || job.status === "PROCESSING");

  const allJobs = jobs ?? [];
  const jobCounts = {
    all: allJobs.length,
    progress: allJobs.filter((j) => j.status === "PENDING" || j.status === "PROCESSING").length,
    DONE: allJobs.filter((j) => j.status === "DONE").length,
    FAILED: allJobs.filter((j) => j.status === "FAILED").length,
  };
  const filteredJobs = allJobs.filter((j) =>
    jobFilter === "all"
      ? true
      : jobFilter === "progress"
        ? j.status === "PENDING" || j.status === "PROCESSING"
        : j.status === jobFilter,
  );

  const JOB_TILES: { value: JobFilter; label: string; count: number; dot: string }[] = [
    { value: "all", label: "All jobs", count: jobCounts.all, dot: "neutral" },
    { value: "progress", label: "In progress", count: jobCounts.progress, dot: "progress" },
    { value: "DONE", label: "Done", count: jobCounts.DONE, dot: "success" },
    { value: "FAILED", label: "Failed", count: jobCounts.FAILED, dot: "danger" },
  ];

  const jobColumns: Column<MappingJob>[] = [
    {
      key: "when",
      header: "Submitted",
      sortValue: (item) => item.createdAt,
      render: (item) => new Date(item.createdAt).toLocaleString(),
    },
    { key: "erp", header: "ERP", sortValue: (item) => item.erpName, render: (item) => <span className="id">{item.erpName}</span> },
    { key: "status", header: "Status", sortValue: (item) => item.status, render: (item) => <StatusBadge status={statusLabel(item.status)} /> },
    {
      key: "output",
      header: "Output",
      render: (item) =>
        item.status === "DONE"
          ? `${item.mapping.length} fields`
          : item.status === "FAILED"
            ? (item.error ?? "Failed")
            : "—",
    },
  ];

  return (
    <>
      <PageHeader
        title="ERP mapping"
        subtitle="Onboard a new ERP: connect it, match its fields to ours, review the proposal, then generate the adapter."
      />

      <Stepper active={activeStep} />

      <form className="panel stack" onSubmit={handleSubmit}>
        <h2>1. Which connection needs a mapping?</h2>
        <p className="hint">
          Only connections with no adapter yet, and no mapping already in progress, show up here — a
          second instance of an ERP that already works never needs this again.
        </p>
        {connectionsError && (
          <div className="callout callout--danger">Could not load connections: {connectionsError.message}</div>
        )}
        <ConnectionPicker connections={connections ?? []} selected={connectionId} onSelect={setConnectionId} />

        <h2>2. Match its fields to ours</h2>
        <h3>Our order fields</h3>
        <p className="hint">
          The fields on an order in this app. Two columns, <code>field,description</code>, one field per row. The
          proposal can only use names from this list.
        </p>
        <div className="actions" role="radiogroup" aria-label="Our order fields">
          <label>
            <input type="radio" name="source" checked={source === "live"} onChange={() => setSource("live")} /> Our order model (live)
          </label>
          <label>
            <input type="radio" name="source" checked={source === "oneoff"} onChange={() => setSource("oneoff")} /> Upload or paste
          </label>
          <label>
            <input type="radio" name="source" checked={source === "registered"} onChange={() => setSource("registered")} /> Saved list
          </label>
          <label>
            <input type="radio" name="source" checked={source === "new"} onChange={() => setSource("new")} /> Save a new list
          </label>
        </div>

        {source === "live" && (
          <div className="field">
            <div className="actions" style={{ justifyContent: "space-between", alignItems: "baseline" }}>
              <p className="hint" style={{ margin: 0 }}>
                Pulled straight from the real order model — add a field there and it shows up here next time.
                Edit a row below if you need to; "Reset to live" discards edits and re-syncs.
              </p>
              {liveFields && liveOrderSchema && (
                <button
                  className="erp-btn erp-btn--ghost erp-btn--sm"
                  type="button"
                  onClick={() => setLiveFields(parseCanonicalCsv(liveOrderSchema))}
                >
                  Reset to live
                </button>
              )}
            </div>
            {liveOrderSchemaLoading && <p className="hint">Loading…</p>}
            {liveFields && (
              <div className="erp-table-wrap">
                <table className="erp-table">
                  <thead>
                    <tr>
                      <th>Field</th>
                      <th>Description</th>
                      <th aria-label="Remove" />
                    </tr>
                  </thead>
                  <tbody>
                    {liveFields.map((f, i) => (
                      <tr key={i}>
                        <td>
                          <input
                            className="input"
                            value={f.field}
                            onChange={(e) => updateLiveField(i, { field: e.target.value })}
                          />
                        </td>
                        <td>
                          <input
                            className="input"
                            value={f.description}
                            onChange={(e) => updateLiveField(i, { description: e.target.value })}
                          />
                        </td>
                        <td>
                          <button
                            className="erp-btn erp-btn--ghost erp-btn--sm"
                            type="button"
                            onClick={() => setLiveFields((prev) => (prev ?? []).filter((_, j) => j !== i))}
                          >
                            Remove
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            <button
              className="erp-btn erp-btn--secondary erp-btn--sm"
              type="button"
              style={{ marginTop: "var(--space-2)" }}
              onClick={() => setLiveFields((prev) => [...(prev ?? []), { field: "", description: "" }])}
            >
              Add field
            </button>
          </div>
        )}

        {source === "registered" && (
          <div className="field">
            <label htmlFor="schema">Saved list</label>
            {(schemas ?? []).length === 0 ? (
              <p className="hint">No saved lists yet. Upload or paste one instead.</p>
            ) : (
              <select className="input" id="schema" value={selectedSchema} onChange={(e) => setSelectedSchema(e.target.value)}>
                <option value="">Choose a list…</option>
                {(schemas ?? []).map((s) => (
                  <option key={s.name} value={s.name}>
                    {s.name} ({s.fieldCount} fields)
                  </option>
                ))}
              </select>
            )}
          </div>
        )}

        {source === "oneoff" && (
          <div className="field">
            <label htmlFor="oneoffFile">Upload a CSV</label>
            <input className="input" id="oneoffFile" type="file" accept=".csv,text/csv" onChange={(e) => loadCsv(e, setOneoffCsv)} />
            <label htmlFor="oneoff">Or paste it</label>
            <textarea
              className="input"
              id="oneoff"
              rows={5}
              placeholder={"field,description\nproduct_key,SKU on the order line\nquantity,Ordered quantity\nclient_reference,Customer purchase order number"}
              value={oneoffCsv}
              onChange={(e) => setOneoffCsv(e.target.value)}
            />
          </div>
        )}

        {source === "new" && (
          <div className="stack">
            <div className="grid2">
              <div className="field">
                <label htmlFor="schemaName">List name</label>
                <input className="input" id="schemaName" value={newSchemaName} onChange={(e) => setNewSchemaName(e.target.value)} />
              </div>
            </div>
            <div className="field">
              <label htmlFor="newCsvFile">Upload a CSV</label>
              <input className="input" id="newCsvFile" type="file" accept=".csv,text/csv" onChange={(e) => loadCsv(e, setNewSchemaCsv)} />
              <label htmlFor="newCsv">Or paste it</label>
              <textarea
                className="input"
                id="newCsv"
                rows={5}
                placeholder={"field,description\nproduct_key,SKU on the order line\nquantity,Ordered quantity\nclient_reference,Customer purchase order number"}
                value={newSchemaCsv}
                onChange={(e) => setNewSchemaCsv(e.target.value)}
              />
            </div>
            <div className="actions">
              <button
                className="erp-btn erp-btn--secondary"
                type="button"
                disabled={!newSchemaName.trim() || !newSchemaCsv.trim() || registerSchema.isPending}
                onClick={handleRegister}
              >
                {registerSchema.isPending ? "Saving…" : "Save list"}
              </button>
            </div>
          </div>
        )}

        <h3>ERP exposed fields</h3>
        <div className="actions" role="radiogroup" aria-label="Sample source">
          <label>
            <input type="radio" name="sampleSource" checked={sampleSource === "files"} onChange={() => setSampleSource("files")} /> Upload
            sample files
          </label>
          <label>
            <input type="radio" name="sampleSource" checked={sampleSource === "live"} onChange={() => setSampleSource("live")} /> Pull samples
            from the connection live
          </label>
        </div>

        {sampleSource === "files" && (
          <div className="field">
            <label htmlFor="samples">JSON or CSV</label>
            <p className="hint">A JSON array of records, or a CSV. Each key, or the CSV header, is the exposed field name.</p>
            <input className="input" id="samples" type="file" accept=".csv,.json" multiple onChange={handleFiles} />
            {sampleFiles.length > 0 && (
              <p className="hint">
                {sampleFiles.length} file(s): {sampleFiles.map((f) => f.filename).join(", ")}
              </p>
            )}
          </div>
        )}

        {sampleSource === "live" && (
          <div className="stack">
            <p className="hint">
              Uses the selected connection's own base URL and credentials — nothing to retype. Pick a small
              number of endpoints to pull a sample from.
            </p>
            <div className="field">
              <div className="actions" style={{ justifyContent: "space-between", alignItems: "baseline" }}>
                <label>Sample requests</label>
                <button
                  className="erp-btn erp-btn--secondary erp-btn--sm"
                  type="button"
                  disabled={
                    !connectionId || !canonicalFieldsReady || suggestRequests.isPending || probe.isPending
                  }
                  onClick={handleSuggestRequests}
                  title={
                    !connectionId
                      ? "Pick a connection in step 1 first"
                      : !canonicalFieldsReady
                        ? "Pick or paste the canonical fields above first — the suggestion is grounded in them"
                        : undefined
                  }
                >
                  <Sparkles size={14} strokeWidth={2} />
                  {suggestRequests.isPending ? "Suggesting…" : probe.isPending ? "Pulling…" : "Suggest & pull"}
                </button>
              </div>
              <p className="hint">
                Not sure which endpoints this ERP exposes? "Suggest & pull" asks the AI for its best guess —
                based on the connection's ERP type and the fields picked above — then immediately fires those
                requests and shows what came back below, so you see real data, not just a guess. Nothing beyond
                a read-only fetch happens automatically; review and edit the rows before "Propose mapping". One
                row per kind of record (e.g. "orders", "invoices"); include a small limit in the path if the ERP
                supports one.
              </p>
              {liveRequests.map((r, i) => (
                <div className="grid2" key={i} style={{ marginBottom: 8 }}>
                  <input
                    className="input"
                    placeholder="Label, e.g. orders"
                    value={r.label}
                    onChange={(e) => setLiveRequests(liveRequests.map((x, j) => (j === i ? { ...x, label: e.target.value } : x)))}
                  />
                  <div style={{ display: "flex", gap: 8 }}>
                    <select
                      className="input"
                      style={{ width: 90 }}
                      value={r.method}
                      onChange={(e) => setLiveRequests(liveRequests.map((x, j) => (j === i ? { ...x, method: e.target.value } : x)))}
                    >
                      <option value="GET">GET</option>
                      <option value="POST">POST</option>
                    </select>
                    <input
                      className="input"
                      placeholder="/orders?limit=5"
                      value={r.path}
                      onChange={(e) => setLiveRequests(liveRequests.map((x, j) => (j === i ? { ...x, path: e.target.value } : x)))}
                    />
                    {liveRequests.length > 1 && (
                      <button
                        className="erp-btn erp-btn--ghost erp-btn--sm"
                        type="button"
                        onClick={() => setLiveRequests(liveRequests.filter((_, j) => j !== i))}
                      >
                        Remove
                      </button>
                    )}
                  </div>
                </div>
              ))}
              <button
                className="erp-btn erp-btn--secondary erp-btn--sm"
                type="button"
                onClick={() => setLiveRequests([...liveRequests, { label: "", method: "GET", path: "" }])}
              >
                Add another
              </button>
            </div>

            <div className="actions">
              <button
                className="erp-btn erp-btn--secondary"
                type="button"
                disabled={!connectionId || !liveReady || probe.isPending}
                onClick={handleTestConnection}
              >
                {probe.isPending ? "Testing…" : "Test connection"}
              </button>
            </div>
            {probePreview && (
              <div className="stack">
                {probePreview.map((s) => (
                  <div key={s.label} className={`callout ${s.error ? "callout--danger" : "callout--info"}`}>
                    <b>{s.label}</b>: {s.error ?? `${s.text?.length ?? 0} characters received`}
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {submit.error && <div className="callout callout--danger">{(submit.error as Error).message}</div>}
        {submitFromProbe.error && <div className="callout callout--danger">{(submitFromProbe.error as Error).message}</div>}
        {schemasError && <div className="callout callout--danger">Could not load schemas: {schemasError.message}</div>}
        <div className="actions">
          <button className="erp-btn erp-btn--primary" type="submit" disabled={!canSubmit || submit.isPending || submitFromProbe.isPending}>
            {submit.isPending || submitFromProbe.isPending ? "Submitting…" : "Propose mapping"}
          </button>
        </div>
      </form>

      <div className="inspector-split">
        <section className="panel stack">
          <div className="panel-head">
            <h2>Jobs</h2>
            {jobId && (
              <button className="erp-btn erp-btn--ghost erp-btn--sm" type="button" onClick={startNewMapping}>
                New mapping
              </button>
            )}
          </div>
          <div className="filtertiles">
            {JOB_TILES.map((t) => (
              <button
                key={t.value}
                type="button"
                className="filtertile"
                aria-pressed={jobFilter === t.value}
                onClick={() => setJobFilter(t.value)}
              >
                <b>{t.count}</b>
                <span>
                  <i className={`tiledot tiledot--${t.dot}`} aria-hidden="true" />
                  {t.label}
                </span>
              </button>
            ))}
          </div>
          {jobsError && <div className="callout callout--danger">Could not load jobs: {jobsError.message}</div>}
          <DataTable
            columns={jobColumns}
            rows={filteredJobs}
            rowKey={(item) => item.jobId}
            isLoading={jobsLoading}
            emptyMessage="No mapping jobs match this filter. Propose one above."
            pageSize={10}
            onRowClick={(item) => {
              setJobId(item.jobId);
              setApproved(false);
            }}
            rowClassName={(item) => (item.jobId === jobId ? "is-selected" : undefined)}
          />
        </section>

        <aside className="panel stack inspector">
          {!job ? (
            <div className="empty-card">
              <Sparkles size={22} strokeWidth={1.75} />
              <p>Select a job to review it.</p>
              <p className="hint">Click a row in the jobs list, or propose a new mapping above.</p>
            </div>
          ) : (
            <>
              <div className="pagehead">
                <div>
                  <h2>
                    Review{" "}
                    <InfoTag text="Each row is the field the ERP sends and the field on our order it becomes. The badge is a plain-English read of the match confidence — check anything marked Needs review or Low confidence by hand before approving." />
                  </h2>
                  <p className="hint">
                    {job.erpName} · <StatusBadge status={statusLabel(job.status)} />
                  </p>
                </div>
              </div>

              {isRunning && <div className="callout callout--info">Mapping in progress. This can take up to a minute.</div>}
              {job.status === "FAILED" && <div className="callout callout--danger">Mapping failed: {job.error}</div>}
              {job.status === "DONE" && mapping.length === 0 && (
                <p className="hint">None of the ERP exposed fields matched our order fields.</p>
              )}

              {job.status === "DONE" && mapping.length > 0 && (
                <>
                  <div className="actions" style={{ gap: "var(--space-4)" }}>
                    <span style={{ color: "var(--status-success-fg)" }}>{tierCounts.high} high</span>
                    <span style={{ color: "var(--status-warning-fg)" }}>{tierCounts.review} review</span>
                    <span style={{ color: "var(--status-danger-fg)" }}>{tierCounts.low} low</span>
                  </div>
                  <div className="maprows">
                    {tiers.map(({ entry, tier }) => (
                      <div className="maprow" key={entry.erpField}>
                        <div className="maprow__top">
                          <span className="maprow__erp">{entry.erpField}</span>
                          <span className={`erp-badge erp-badge--${tier.role}`}>{entry.confidence}%</span>
                        </div>
                        <span className="maprow__ours">
                          → becomes <b>{entry.canonicalField}</b>
                        </span>
                        {entry.sampleData && <span className="maprow__example">e.g. {entry.sampleData}</span>}
                      </div>
                    ))}
                  </div>
                  <div className="actions">
                    <button
                      className="erp-btn erp-btn--ghost erp-btn--sm"
                      type="button"
                      onClick={() => downloadBlob(`${job.erpName}_mapping.json`, JSON.stringify(mapping, null, 2), "application/json")}
                    >
                      Download JSON
                    </button>
                    <button
                      className="erp-btn erp-btn--ghost erp-btn--sm"
                      type="button"
                      onClick={() => downloadBlob(`${job.erpName}_mapping.csv`, toCsv(mapping), "text/csv")}
                    >
                      Download CSV
                    </button>
                  </div>
                </>
              )}

              <hr className="rule" />

              <h3>Approve and generate the adapter</h3>
              <p className="hint">
                This is the gate. Approving sends the mapping above, unchanged, to the code generator. It writes
                the adapter and opens a pull request. Fix a wrong row before you approve. There is no second check.
              </p>
              <div className="actions">
                <button
                  className="erp-btn erp-btn--primary"
                  type="button"
                  disabled={job.status !== "DONE" || mapping.length === 0 || approve.isPending || runEnabled}
                  onClick={async () => {
                    if (!jobId) return;
                    await approve.mutateAsync({ jobId });
                    setApproved(true);
                  }}
                >
                  {approve.isPending ? "Approving…" : runEnabled ? "Approved" : "Approve and generate code"}
                </button>
              </div>
              {job.status !== "DONE" && <p className="hint">The button stays off until a proposal is ready to review.</p>}
              {approve.error && <div className="callout callout--danger">{(approve.error as Error).message}</div>}
              {run && (
                <div className="callout callout--info">
                  Code generation: <StatusBadge status={statusLabel(run.status)} />
                  {run.status === "FAILED" && <> — {run.error}</>}
                  {(run.status === "PENDING" || run.status === "PROCESSING") && (
                    <p className="hint">
                      Writing the adapter is the long step. It often takes several minutes, and it is stopped if it
                      is still running after 30.
                    </p>
                  )}
                  {run.status === "DONE" && (
                    <>
                      {" "}
                      — branch <code>{run.branch}</code>{" "}
                      {run.prUrl && (
                        <a href={run.prUrl} target="_blank" rel="noreferrer">
                          open pull request
                        </a>
                      )}
                    </>
                  )}
                </div>
              )}
            </>
          )}
        </aside>
      </div>
    </>
  );
}
