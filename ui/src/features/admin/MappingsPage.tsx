import { useState, type ChangeEvent, type FormEvent } from "react";

import { DataTable, type Column } from "../../components/DataTable";
import { InfoTag } from "../../components/InfoTag";
import { StatusBadge } from "../../components/StatusBadge";
import type { MappingEntry } from "../../api/queries/mapping";
import {
  useAdapterRun,
  useApproveMapping,
  useCanonicalSchemas,
  useMappingJob,
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
  const registerSchema = useRegisterCanonicalSchema();
  const submit = useSubmitMapping();
  const approve = useApproveMapping();

  const [source, setSource] = useState<Source>("registered");
  const [selectedSchema, setSelectedSchema] = useState("");
  const [newSchemaName, setNewSchemaName] = useState("");
  const [newSchemaCsv, setNewSchemaCsv] = useState("");
  const [oneoffCsv, setOneoffCsv] = useState("");
  const [erpName, setErpName] = useState("");
  const [sampleFiles, setSampleFiles] = useState<SampleFile[]>([]);
  const [jobId, setJobId] = useState<string | null>(null);
  const [approved, setApproved] = useState(false);

  const { data: job } = useMappingJob(jobId);
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

  const columns: Column<MappingEntry>[] = [
    { key: "erp", header: "ERP field", render: (m) => <span className="id">{m.erpField}</span> },
    { key: "canonical", header: "Canonical field", render: (m) => m.canonicalField },
    { key: "sample", header: "Sample value", render: (m) => <span className="muted">{m.sampleData}</span> },
    {
      key: "confidence",
      header: (
        <>
          Confidence <InfoTag text="0-100, calibrated strict. Treat anything below about 95 as something to check by hand." />
        </>
      ),
      align: "right",
      render: (m) => `${m.confidence}`,
    },
  ];

  const mapping = job?.mapping ?? [];
  const isRunning = !!jobId && (!job || job.status === "PENDING" || job.status === "PROCESSING");

  return (
    <>
      <div className="pagehead">
        <div>
          <h1>ERP mapping</h1>
          <p>
            Propose how a new ERP&apos;s fields map onto your canonical fields. Upload the ERP&apos;s sample
            export(s), review the draft the model returns, then approve it to have the adapter implemented.
          </p>
        </div>
      </div>

      <form className="panel stack" onSubmit={handleSubmit}>
        <h2>1. Canonical fields</h2>
        <div className="actions" role="radiogroup" aria-label="Canonical field source">
          <label>
            <input type="radio" name="source" checked={source === "registered"} onChange={() => setSource("registered")} /> Use a
            registered schema
          </label>
          <label>
            <input type="radio" name="source" checked={source === "oneoff"} onChange={() => setSource("oneoff")} /> Paste a one-off CSV
          </label>
          <label>
            <input type="radio" name="source" checked={source === "new"} onChange={() => setSource("new")} /> Register a new schema
          </label>
        </div>

        {source === "registered" && (
          <div className="field">
            <label htmlFor="schema">Registered schema</label>
            <select className="input" id="schema" value={selectedSchema} onChange={(e) => setSelectedSchema(e.target.value)}>
              <option value="">Choose a schema…</option>
              {(schemas ?? []).map((s) => (
                <option key={s.name} value={s.name}>
                  {s.name} ({s.fieldCount} fields)
                </option>
              ))}
            </select>
          </div>
        )}

        {source === "oneoff" && (
          <div className="field">
            <label htmlFor="oneoff">
              Canonical fields CSV <InfoTag text="Two columns: field,description. One row per canonical field." />
            </label>
            <textarea
              className="input"
              id="oneoff"
              rows={5}
              placeholder={"field,description\norder_id,The order's unique id\ncustomer,End customer name"}
              value={oneoffCsv}
              onChange={(e) => setOneoffCsv(e.target.value)}
            />
          </div>
        )}

        {source === "new" && (
          <div className="stack">
            <div className="grid2">
              <div className="field">
                <label htmlFor="schemaName">Schema name</label>
                <input className="input" id="schemaName" value={newSchemaName} onChange={(e) => setNewSchemaName(e.target.value)} />
              </div>
            </div>
            <div className="field">
              <label htmlFor="newCsv">
                Canonical fields CSV <InfoTag text="Two columns: field,description. Saved under the schema name for reuse." />
              </label>
              <textarea
                className="input"
                id="newCsv"
                rows={5}
                placeholder={"field,description\norder_id,The order's unique id\ncustomer,End customer name"}
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
                {registerSchema.isPending ? "Saving…" : "Register schema"}
              </button>
            </div>
          </div>
        )}

        <h2>2. ERP sample export(s)</h2>
        <div className="grid2">
          <div className="field">
            <label htmlFor="erpName">ERP name</label>
            <input className="input" id="erpName" placeholder="e.g. NetSuite" value={erpName} onChange={(e) => setErpName(e.target.value)} />
          </div>
          <div className="field">
            <label htmlFor="samples">
              Sample files <InfoTag text="One or more CSV or JSON-array exports. Read in your browser; only a truncated sample is sent." />
            </label>
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

      {jobId && job && (
        <div className="panel stack">
          <div className="pagehead">
            <div>
              <h2>Proposed mapping</h2>
              <p className="hint">
                {job.erpName} · <StatusBadge status={statusLabel(job.status)} />
              </p>
            </div>
            {job.status === "DONE" && mapping.length > 0 && (
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

          {job.status === "FAILED" && <div className="callout callout--danger">Mapping failed: {job.error}</div>}

          {job.status === "DONE" && (
            <DataTable
              columns={columns}
              rows={mapping}
              rowKey={(m) => m.erpField}
              emptyMessage="No fields matched the canonical schema."
            />
          )}

          {isRunning && <div className="callout callout--info">Mapping in progress — this can take up to a minute.</div>}

          {job.status === "DONE" && mapping.length > 0 && (
            <div className="stack">
              <h2>Approve &amp; implement</h2>
              <p className="hint">
                Review the mapping above first. Approving hands it as-is to the adapter-codegen service, which implements the
                adapter and opens a pull request — nothing re-checks it, so fix anything wrong before approving.
              </p>
              <div className="actions">
                <button
                  className="erp-btn erp-btn--primary"
                  type="button"
                  disabled={approve.isPending || runEnabled}
                  onClick={async () => {
                    await approve.mutateAsync({ jobId });
                    setApproved(true);
                  }}
                >
                  {approve.isPending ? "Approving…" : runEnabled ? "Approved" : "Approve & implement"}
                </button>
              </div>
              {run && (
                <div className="callout callout--info">
                  Adapter run: <StatusBadge status={statusLabel(run.status)} />
                  {run.status === "FAILED" && <> — {run.error}</>}
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
            </div>
          )}
        </div>
      )}
    </>
  );
}
