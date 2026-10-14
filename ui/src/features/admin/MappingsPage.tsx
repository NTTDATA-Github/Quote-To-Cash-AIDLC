import { useState, type ChangeEvent, type FormEvent } from "react";
import { ArrowRight } from "lucide-react";

import { DataTable, type Column } from "../../components/DataTable";
import { InfoTag } from "../../components/InfoTag";
import { PageHeader } from "../../components/PageHeader";
import { StatusBadge, type Role } from "../../components/StatusBadge";
import type { MappingEntry, MappingJob } from "../../api/queries/mapping";
import {
  useAdapterRun,
  useApproveMapping,
  useCanonicalSchemas,
  useMappingJobs,
  useRegisterCanonicalSchema,
  useSubmitMapping,
  type SampleFile,
} from "../../hooks/useMapping";

type Source = "registered" | "oneoff" | "new";

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

export function MappingsPage() {
  const { data: schemas, error: schemasError } = useCanonicalSchemas();
  const { data: jobs, error: jobsError, isLoading: jobsLoading } = useMappingJobs();
  const registerSchema = useRegisterCanonicalSchema();
  const submit = useSubmitMapping();
  const approve = useApproveMapping();

  const [source, setSource] = useState<Source>("oneoff");
  const [selectedSchema, setSelectedSchema] = useState("");
  const [newSchemaName, setNewSchemaName] = useState("");
  const [newSchemaCsv, setNewSchemaCsv] = useState("");
  const [oneoffCsv, setOneoffCsv] = useState("");
  const [erpName, setErpName] = useState("");
  const [sampleFiles, setSampleFiles] = useState<SampleFile[]>([]);
  const [jobId, setJobId] = useState<string | null>(null);
  const [approved, setApproved] = useState(false);

  const job = (jobs ?? []).find((item) => item.jobId === jobId) ?? null;
  const runEnabled = approved || !!job?.adapterRunId;
  const { data: run } = useAdapterRun(jobId, runEnabled);

  const canSubmit =
    !!erpName.trim() &&
    sampleFiles.length > 0 &&
    ((source === "registered" && !!selectedSchema) || (source === "oneoff" && !!oneoffCsv.trim()));

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

  // Clicking a job row pins the Review/Approve sections to that job (by design, so you
  // can go back and inspect past jobs) — this is the way out of that, back to a blank
  // proposal, without a page reload.
  function startNewMapping() {
    setJobId(null);
    setApproved(false);
    setSource("oneoff");
    setSelectedSchema("");
    setNewSchemaName("");
    setNewSchemaCsv("");
    setOneoffCsv("");
    setErpName("");
    setSampleFiles([]);
  }

  async function handleRegister() {
    await registerSchema.mutateAsync({ name: newSchemaName.trim(), csvText: newSchemaCsv });
    setSource("registered");
    setSelectedSchema(newSchemaName.trim());
    setNewSchemaName("");
    setNewSchemaCsv("");
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setApproved(false);
    const result = await submit.mutateAsync({
      erpName: erpName.trim(),
      sampleFiles,
      schemaName: source === "registered" ? selectedSchema : null,
      canonicalFieldsCsv: source === "oneoff" ? oneoffCsv : null,
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

  const jobColumns: Column<MappingJob>[] = [
    {
      key: "when",
      header: "Submitted",
      render: (item) => new Date(item.createdAt).toLocaleString(),
    },
    { key: "erp", header: "ERP", render: (item) => <span className="id">{item.erpName}</span> },
    {
      key: "input",
      header: "Input",
      render: (item) => (
        <span>
          {item.schemaName ?? "One-off list"}
          {item.sampleFiles.length > 0 ? ` · ${item.sampleFiles.join(", ")}` : ""}
        </span>
      ),
    },
    { key: "status", header: "Status", render: (item) => <StatusBadge status={statusLabel(item.status)} /> },
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
    {
      key: "code",
      header: "Code",
      render: (item) => {
        if (item.jobId === jobId && run?.status === "DONE" && run.prUrl) {
          return (
            <a href={run.prUrl} target="_blank" rel="noreferrer">
              Pull request
            </a>
          );
        }
        if (item.jobId === jobId && run) return statusLabel(run.status);
        // Only the selected row's live code-gen status is fetched (it's an external call) —
        // for every other row we only know a run was started, not whether it's done.
        return item.adapterRunId ? "Approved — click for status" : "—";
      },
    },
  ];

  return (
    <>
      <PageHeader
        title="ERP mapping"
        subtitle="Match our order fields to the ERP exposed fields, review the proposal, then approve it — approval sends the mapping to the code generator, which writes the adapter and opens a pull request."
      />

      <section className="panel stack">
        <div className="panel-head">
          <h2>Jobs</h2>
          {jobId && (
            <button className="erp-btn erp-btn--ghost erp-btn--sm" type="button" onClick={startNewMapping}>
              New mapping
            </button>
          )}
        </div>
        {jobsError && <div className="callout callout--danger">Could not load jobs: {jobsError.message}</div>}
        <DataTable
          columns={jobColumns}
          rows={jobs ?? []}
          rowKey={(item) => item.jobId}
          isLoading={jobsLoading}
          emptyMessage="No mapping jobs yet. Propose one below."
          onRowClick={(item) => {
            setJobId(item.jobId);
            setApproved(false);
          }}
          rowClassName={(item) => (item.jobId === jobId ? "is-selected" : undefined)}
        />
      </section>

      <form className="panel stack" onSubmit={handleSubmit}>
        <h2>1. Propose a mapping</h2>
        <h3>Our order fields</h3>
        <p className="hint">
          The fields on an order in this app. Two columns, <code>field,description</code>, one field per row. The
          proposal can only use names from this list.
        </p>
        <div className="actions" role="radiogroup" aria-label="Our order fields">
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
        <p className="hint">
          A JSON array of records, or a CSV. Each key, or the CSV header, is the exposed field name, with a few
          example values. A different ERP is a separate job.
        </p>
        <div className="grid2">
          <div className="field">
            <label htmlFor="erpName">ERP</label>
            <input className="input" id="erpName" placeholder="e.g. SAP" value={erpName} onChange={(e) => setErpName(e.target.value)} />
          </div>
          <div className="field">
            <label htmlFor="samples">JSON or CSV</label>
            <input className="input" id="samples" type="file" accept=".csv,.json" multiple onChange={handleFiles} />
          </div>
        </div>
        {sampleFiles.length > 0 && (
          <p className="hint">
            {sampleFiles.length} file(s): {sampleFiles.map((f) => f.filename).join(", ")}
          </p>
        )}

        {submit.error && <div className="callout callout--danger">{(submit.error as Error).message}</div>}
        {schemasError && <div className="callout callout--danger">Could not load schemas: {schemasError.message}</div>}
        <div className="actions">
          <button className="erp-btn erp-btn--primary" type="submit" disabled={!canSubmit || submit.isPending}>
            {submit.isPending ? "Submitting…" : "Propose mapping"}
          </button>
        </div>
      </form>

      <section className="panel stack">
        <div className="pagehead">
          <div>
            <h2>
              2. Review the proposal{" "}
              <InfoTag text="Each row reads as a sentence: the field the ERP sends becomes a field on our order. The badge is a plain-English read of the match confidence — check anything marked Needs review or Low confidence by hand before approving." />
            </h2>
            <p className="hint">
              {job ? (
                <>
                  {job.erpName} · <StatusBadge status={statusLabel(job.status)} />
                </>
              ) : (
                "Nothing proposed yet."
              )}
            </p>
          </div>
          {job?.status === "DONE" && mapping.length > 0 && (
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
          )}
        </div>
        {isRunning && <div className="callout callout--info">Mapping in progress. This can take up to a minute.</div>}
        {job?.status === "FAILED" && <div className="callout callout--danger">Mapping failed: {job.error}</div>}
        {job?.status === "DONE" && mapping.length === 0 && <p className="hint">None of the ERP exposed fields matched our order fields.</p>}
        {job?.status === "DONE" && mapping.length > 0 && (
          <>
            <div className="statgrid">
              <div className="stat">
                <b style={{ color: "var(--status-success-fg)" }}>{tierCounts.high}</b>
                <span>High confidence</span>
              </div>
              <div className="stat">
                <b style={{ color: "var(--status-warning-fg)" }}>{tierCounts.review}</b>
                <span>Needs review</span>
              </div>
              <div className="stat">
                <b style={{ color: "var(--status-danger-fg)" }}>{tierCounts.low}</b>
                <span>Low confidence</span>
              </div>
            </div>
            <div className="mapflow">
              {tiers.map(({ entry, tier }) => (
                <div className="mapflow-row" key={entry.erpField}>
                  <div className="mapflow-field">
                    <span className="label">The ERP sends</span>
                    <span className="mapflow-name mono">{entry.erpField}</span>
                    {entry.sampleData && <span className="mapflow-example muted">e.g. {entry.sampleData}</span>}
                  </div>
                  <div className="mapflow-link">
                    <ArrowRight size={18} strokeWidth={2} />
                    <span className={`erp-badge erp-badge--${tier.role}`}>
                      {tier.label} · {entry.confidence}%
                    </span>
                  </div>
                  <div className="mapflow-field mapflow-field--ours">
                    <span className="label">Becomes</span>
                    <span className="mapflow-name">{entry.canonicalField}</span>
                  </div>
                </div>
              ))}
            </div>
          </>
        )}
      </section>

      <section className="panel stack">
        <h2>3. Approve and generate the adapter</h2>
        <p className="hint">
          This is the gate. Approving sends the mapping above, unchanged, to the code generator. It writes the adapter and
          opens a pull request. Fix a wrong row before you approve. There is no second check.
        </p>
        <div className="actions">
          <button
            className="erp-btn erp-btn--primary"
            type="button"
            disabled={!jobId || job?.status !== "DONE" || mapping.length === 0 || approve.isPending || runEnabled}
            onClick={async () => {
              if (!jobId) return;
              await approve.mutateAsync({ jobId });
              setApproved(true);
            }}
          >
            {approve.isPending ? "Approving…" : runEnabled ? "Approved" : "Approve and generate code"}
          </button>
        </div>
        {job?.status !== "DONE" && <p className="hint">The button stays off until a proposal is ready to review.</p>}
        {run && (
          <div className="callout callout--info">
            Code generation: <StatusBadge status={statusLabel(run.status)} />
            {run.status === "FAILED" && <> — {run.error}</>}
            {(run.status === "PENDING" || run.status === "PROCESSING") && (
              <p className="hint">
                Writing the adapter is the long step. It often takes several minutes, and it is stopped if it is still
                running after 30.
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
      </section>
    </>
  );
}
